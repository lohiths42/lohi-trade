"""User-upload watch-folder source (Req 3.1, design §3.2).

Watches a configured directory (default ``data/research/uploads/``) for
newly created ``.pdf`` files and publishes one index event per file onto
:data:`RESEARCH_INDEX_EVENTS_STREAM`. Filenames follow the convention
``SYMBOL__<anything>.pdf`` (two underscores separate the ticker from the
free-form suffix); the ``SYMBOL`` prefix becomes the event's ``symbol``
field.

Event payload shape (design §3.2, §4.3)::

    {
        "document_url": "file://<absolute path to PDF>",
        "symbol": "<ticker from filename prefix, upper-case>",
        "document_type": "user_upload",
        "published_at": "<ISO-8601 timestamp, UTC — upload time>",
        "source": "user_upload",
        "user_id": "<UUID resolved by user_id_resolver>",
    }

The ``user_id`` field is appended on top of the canonical four-field
shape because user-uploaded files are the only source that can be
attributed to a specific user at ingest time; the downstream indexer
uses it to populate :class:`research_documents.user_id` for RLS
enforcement (Req 4.6). BSE/NSE feeds are system-wide and leave user
attribution to the per-user watchlist fan-out at snapshot time
(design §3.10).

Design reference
----------------
* :file:`.kiro/specs/lohi-research-dashboard/design.md` §3.2.

Satisfies
---------
* **Req 3.1** — ingest user-uploaded PDFs in a watch folder.

Integration caveats
-------------------
* ``watchdog`` is not in the top-level ``requirements.txt``; it is
  imported lazily inside :meth:`UserUploadWatcher.start` so that simply
  importing this module does not fail on a bare install (the factory
  can still be inspected, types resolved, etc.). Operators enable the
  watch-folder feature by installing ``watchdog`` alongside the
  ``research-indexer`` worker.
* The watchdog observer threading model is synchronous by design. The
  handler bridges into the asyncio loop via
  :func:`asyncio.run_coroutine_threadsafe` — the loop is captured when
  :meth:`start` is called so the handler can schedule its ``xadd`` calls
  back onto it.
* ``user_id_resolver`` is an injected callback owned by the gateway; it
  accepts the *filename* (not the full path) and returns a
  :class:`uuid.UUID`. Uploads for which it raises or returns ``None``
  are skipped with a WARNING log — the gateway is free to implement
  per-user subdirectories, a sidecar ``.json`` metadata file, or any
  other scheme (Task 5.4 only wires the dependency; concrete resolution
  lives in later tasks).
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Final
from uuid import UUID

from src.research.constants import RESEARCH_INDEX_EVENTS_STREAM
from src.utils.logger import ComponentLogger, get_logger

_LOGGER_COMPONENT: Final[str] = "UserUploadWatcher"
_SOURCE_TAG: Final[str] = "user_upload"
_DOCUMENT_TYPE: Final[str] = "user_upload"
_FILENAME_SEPARATOR: Final[str] = "__"

UserIdResolver = Callable[[str], UUID | None]


class UserUploadWatcher:
    """Watchdog-backed watcher for the user-upload PDF directory.

    Lifecycle
    ---------
    * :meth:`start` — spin up the watchdog :class:`Observer`, remember
      the running asyncio event loop, and return once the watcher is
      armed.
    * :meth:`stop` — signal the observer to stop and join its thread.
    * ``on_created`` callbacks on the internal
      :class:`watchdog.events.FileSystemEventHandler` bridge into the
      captured asyncio loop with
      :func:`asyncio.run_coroutine_threadsafe`, so ``redis_client.xadd``
      is awaited on the same loop that owns it.

    Parameters
    ----------
    watch_dir:
        Absolute or relative path to the watched directory. Created if
        missing (watchdog refuses to start on a non-existent path).
    redis_client:
        Async Redis client. Not owned by this class.
    user_id_resolver:
        Callback from filename to :class:`uuid.UUID`. See module
        docstring.
    """

    def __init__(
        self,
        *,
        watch_dir: str,
        redis_client: Any,
        user_id_resolver: UserIdResolver,
    ) -> None:
        self._watch_dir: Path = Path(watch_dir).resolve()
        self._redis = redis_client
        self._user_id_resolver = user_id_resolver
        self._logger: ComponentLogger = get_logger(_LOGGER_COMPONENT)
        # Populated in ``start``; left as ``None`` so that accidental
        # misuse (``stop`` before ``start``) is a loud no-op.
        self._observer: Any | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Arm the watchdog observer.

        Must be called from inside a running asyncio event loop because
        the file-system callbacks schedule coroutines onto it via
        :func:`asyncio.run_coroutine_threadsafe`.
        """
        # Lazy import — watchdog is an optional dep (see module
        # docstring).
        from watchdog.events import FileSystemEventHandler  # noqa: PLC0415
        from watchdog.observers import Observer  # noqa: PLC0415

        self._watch_dir.mkdir(parents=True, exist_ok=True)
        self._loop = asyncio.get_running_loop()

        watcher = self

        class _Handler(FileSystemEventHandler):
            """Watchdog callback → asyncio bridge."""

            def on_created(self, event: Any) -> None:  # noqa: D401
                if event.is_directory:
                    return
                src_path = getattr(event, "src_path", None)
                if not src_path or not src_path.lower().endswith(".pdf"):
                    return
                watcher._on_pdf_created(src_path)

        self._observer = Observer()
        self._observer.schedule(_Handler(), str(self._watch_dir), recursive=False)
        self._observer.start()

        self._logger.info(
            "User-upload watcher started",
            extra={"watch_dir": str(self._watch_dir)},
        )

    def stop(self) -> None:
        """Stop the watchdog observer and join its thread."""
        if self._observer is None:
            return
        self._observer.stop()
        self._observer.join()
        self._observer = None
        self._logger.info(
            "User-upload watcher stopped",
            extra={"watch_dir": str(self._watch_dir)},
        )

    # ------------------------------------------------------------------
    # Internal handler
    # ------------------------------------------------------------------

    def _on_pdf_created(self, src_path: str) -> None:
        """Schedule :meth:`_publish_event` on the asyncio loop.

        Runs on the watchdog observer thread, so we cannot ``await``
        anything here. We validate inputs synchronously so a malformed
        filename never touches the loop at all.
        """
        filename = os.path.basename(src_path)
        symbol = _symbol_from_filename(filename)
        if symbol is None:
            self._logger.warning(
                "Ignoring uploaded PDF with unrecognised filename prefix",
                extra={"filename": filename, "expected": "SYMBOL__<name>.pdf"},
            )
            return

        try:
            user_id = self._user_id_resolver(filename)
        except Exception as exc:  # noqa: BLE001 — operator-supplied callback
            self._logger.warning(
                "user_id_resolver raised for uploaded PDF; skipping",
                extra={
                    "filename": filename,
                    "error_class": type(exc).__name__,
                    "error": str(exc),
                },
            )
            return

        if user_id is None:
            self._logger.warning(
                "user_id_resolver returned None for uploaded PDF; skipping",
                extra={"filename": filename},
            )
            return

        loop = self._loop
        if loop is None:
            # ``start`` has not run (shouldn't happen — observer runs on
            # a thread we spawned inside ``start``) or ``stop`` has
            # already torn it down.
            return

        absolute = os.path.abspath(src_path)
        event = {
            "document_url": f"file://{absolute}",
            "symbol": symbol,
            "document_type": _DOCUMENT_TYPE,
            "published_at": datetime.now(tz=timezone.utc).isoformat(),
            "source": _SOURCE_TAG,
            "user_id": str(user_id),
        }

        asyncio.run_coroutine_threadsafe(self._publish_event(event), loop)

    async def _publish_event(self, event: dict[str, str]) -> None:
        """XADD *event* onto :data:`RESEARCH_INDEX_EVENTS_STREAM`."""
        try:
            await self._redis.xadd(RESEARCH_INDEX_EVENTS_STREAM, event)
        except Exception as exc:  # noqa: BLE001 — log + swallow
            self._logger.error(
                "Failed to publish user-upload index event",
                extra={
                    "event": event,
                    "error_class": type(exc).__name__,
                    "error": str(exc),
                },
                exc_info=True,
            )
            return
        self._logger.info(
            "Published user-upload index event",
            extra={"symbol": event["symbol"], "document_url": event["document_url"]},
        )


def _symbol_from_filename(filename: str) -> str | None:
    """Return the uppercase symbol parsed from ``SYMBOL__*.pdf``.

    Returns ``None`` when *filename* does not match the convention —
    missing double-underscore, empty prefix, or non-``.pdf`` extension.
    """
    if not filename.lower().endswith(".pdf"):
        return None
    stem = filename[: -len(".pdf")]
    if _FILENAME_SEPARATOR not in stem:
        return None
    prefix, _, _remainder = stem.partition(_FILENAME_SEPARATOR)
    prefix = prefix.strip()
    if not prefix:
        return None
    return prefix.upper()


async def build(
    cfg: dict,
    redis_client: Any,
    *,
    user_id_resolver: UserIdResolver | None = None,
) -> UserUploadWatcher:
    """Factory entry point.

    Parameters
    ----------
    cfg:
        The ``research.ingest.sources.user_uploads`` block. Recognised
        keys: ``watch_dir`` (default ``data/research/uploads``).
    redis_client:
        Async Redis client.
    user_id_resolver:
        Callback ``(filename: str) -> UUID | None``. Required — the
        factory does not attempt any default resolution because the
        concrete scheme is deployment-specific (see module docstring).
    """
    if user_id_resolver is None:
        raise ValueError(
            "user_uploads.build requires a user_id_resolver callback; the "
            "gateway wires this at startup (design §3.2)."
        )
    return UserUploadWatcher(
        watch_dir=str(cfg.get("watch_dir", "data/research/uploads")),
        redis_client=redis_client,
        user_id_resolver=user_id_resolver,
    )


__all__ = ["UserUploadWatcher", "UserIdResolver", "build"]
