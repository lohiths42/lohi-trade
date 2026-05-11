"""``research-indexer`` worker entrypoint (Task 18.1, design §2.2, §16.1).

Long-lived asyncio process that polls the BSE/NSE announcement feeds
and watches the user-upload directory, publishing index events onto
:data:`RESEARCH_INDEX_EVENTS_STREAM` for the downstream chunk-and-embed
pipeline. Wraps the concrete poller implementations in
:mod:`src.research.ingest.sources` (Tasks 5.2–5.4) into a single
supervised process.

Roles per design §2.2:

1. **BSE feed poller** — periodic JSON pull, publishes events per
   new announcement (Task 5.2, :class:`BseFeedPoller`).
2. **NSE feed poller** — same shape against NSE (Task 5.3,
   :class:`NseFeedPoller`).
3. **User-upload watcher** — ``watchdog`` observer on
   ``data/research/uploads/`` (Task 5.4, :class:`UserUploadWatcher`).

The worker does not own the chunk/embed/upsert pipeline — that runs
on a separate consumer of ``research:index_events`` (Phase 5). This
module's job is purely to *produce* index events; a downstream
process transforms them into :class:`ChunkRecord`\\s in the active
:class:`VectorStore`.

Graceful degradation
--------------------
Each source is started behind a ``try``/``except`` so a missing
optional dependency (e.g. ``watchdog`` not installed) disables just
that source, not the whole worker. The BSE/NSE pollers need only
``httpx`` which is already a gateway dependency; the user-upload
watcher needs ``watchdog`` which is optional.

Config
------
Reads the ``research.ingest.sources.*`` blocks from
``config/settings.yaml`` via :mod:`src.utils.config_loader`. When the
loader is unavailable (trimmed-install test runs) the worker falls
back to sensible defaults so ``python -m src.research.workers.indexer
--once`` still exits cleanly.

Satisfies
---------
* Req 7.1 — ``start-research.sh`` supervises this process.
* Design §2.2 — ``research-indexer`` runtime role.
* Design §16.1 — launcher wrapping Tasks 5.2–5.4.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
from typing import Any, Final

from src.research.constants import RESEARCH_INDEX_EVENTS_STREAM

try:  # pragma: no cover - trimmed-install fallback
    from src.utils.logger import get_logger

    _logger: Any = get_logger("ResearchIndexerWorker")
except Exception:  # noqa: BLE001
    _logger = logging.getLogger("research.workers.indexer")


# How often the worker wakes to check whether the stop_event has been
# flipped while the pollers are idle in their own sleep loops.
_SUPERVISOR_TICK_SEC: Final[float] = 1.0


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for the worker."""
    parser = argparse.ArgumentParser(
        prog="research-indexer",
        description=(
            "Lohi-Research indexer worker (design §2.2). Polls BSE/NSE "
            "feeds and watches data/research/uploads/; publishes to "
            "research:index_events."
        ),
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single poll iteration against each source then exit.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entrypoint invoked by ``start-research.sh``.

    Returns an OS exit code. The launcher restarts non-zero exits.
    """
    args = _parse_args(argv)
    try:
        asyncio.run(_run_worker(once=args.once))
    except KeyboardInterrupt:
        _log_info("indexer worker interrupted; shutting down")
        return 0
    except Exception as exc:  # noqa: BLE001
        _log_warning(
            "indexer worker crashed",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return 1
    return 0


# --------------------------------------------------------------------------- #
# Worker body                                                                 #
# --------------------------------------------------------------------------- #


async def _run_worker(*, once: bool = False) -> None:
    """Main worker loop — start every enabled source and wait for shutdown."""
    settings = _load_settings()
    ingest_cfg = _ingest_config(settings)

    redis_url = _resolve_redis_url(settings)
    redis_client = await _connect_redis(redis_url)
    if redis_client is None:
        _log_warning(
            "indexer worker cannot start; redis unavailable",
            redis_url=redis_url,
        )
        return

    _log_info(
        "indexer worker starting",
        stream=RESEARCH_INDEX_EVENTS_STREAM,
        redis_url=redis_url,
    )

    stop_event = asyncio.Event()
    _install_signal_handlers(stop_event)

    tasks: list[asyncio.Task[None]] = []
    watchers: list[Any] = []  # for synchronous shutdown

    try:
        # 1) BSE feed poller (Task 5.2).
        bse_cfg = _sources_block(ingest_cfg, "bse_feed")
        if bse_cfg.get("enabled", True):
            bse_task = await _start_bse_poller(
                bse_cfg, redis_client, settings, once=once,
            )
            if bse_task is not None:
                tasks.append(bse_task)

        # 2) NSE feed poller (Task 5.3).
        nse_cfg = _sources_block(ingest_cfg, "nse_feed")
        if nse_cfg.get("enabled", True):
            nse_task = await _start_nse_poller(
                nse_cfg, redis_client, settings, once=once,
            )
            if nse_task is not None:
                tasks.append(nse_task)

        # 3) User-upload watcher (Task 5.4) — long-lived filesystem
        # observer; its thread lives outside asyncio but the async
        # side only has to keep a reference to call ``stop()`` on
        # shutdown.
        uploads_cfg = _sources_block(ingest_cfg, "user_uploads")
        if uploads_cfg.get("enabled", True):
            watcher = await _start_user_uploads_watcher(
                uploads_cfg, redis_client,
            )
            if watcher is not None:
                watchers.append(watcher)

        if once:
            # One-shot mode — everything has already run its single
            # iteration. Drain async tasks and return.
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            return

        # Supervisor loop — idle while the pollers + watchers do
        # their own work on background tasks / threads.
        while not stop_event.is_set():
            await asyncio.wait(
                [asyncio.create_task(stop_event.wait())],
                timeout=_SUPERVISOR_TICK_SEC,
            )
    finally:
        _log_info("indexer worker draining")
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for w in watchers:
            try:
                w.stop()
            except Exception:  # noqa: BLE001 - best-effort
                pass
        try:
            await redis_client.aclose()
        except Exception:  # noqa: BLE001 - best-effort
            pass
        _log_info("indexer worker stopped")


# --------------------------------------------------------------------------- #
# Source-specific starters                                                    #
# --------------------------------------------------------------------------- #


async def _start_bse_poller(
    cfg: dict,
    redis_client: Any,
    settings: dict,
    *,
    once: bool,
) -> asyncio.Task[None] | None:
    """Build and launch the BSE poller (Task 5.2)."""
    try:
        from src.research.ingest.robots import RobotsChecker  # noqa: PLC0415
        from src.research.ingest.sources.bse_feed import build  # noqa: PLC0415
    except ImportError as exc:
        _log_warning(
            "BSE poller unavailable (import failure); skipping",
            error=str(exc),
        )
        return None

    poller_cfg = dict(cfg)
    poller_cfg.setdefault("watchlist_symbols", settings.get("symbols", []))
    robots = RobotsChecker()
    try:
        poller = await build(poller_cfg, redis_client, robots=robots)
    except Exception as exc:  # noqa: BLE001
        _log_warning(
            "BSE poller construction failed; skipping",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return None

    if once:
        try:
            await poller.poll_once()
        except Exception as exc:  # noqa: BLE001
            _log_warning(
                "BSE poll_once failed",
                error_type=type(exc).__name__,
                error=str(exc),
            )
        # No ongoing task — return ``None`` so the supervisor knows.
        return None

    return asyncio.create_task(poller.run_forever(), name="bse-feed-poller")


async def _start_nse_poller(
    cfg: dict,
    redis_client: Any,
    settings: dict,
    *,
    once: bool,
) -> asyncio.Task[None] | None:
    """Build and launch the NSE poller (Task 5.3)."""
    try:
        from src.research.ingest.robots import RobotsChecker  # noqa: PLC0415
        from src.research.ingest.sources.nse_feed import build  # noqa: PLC0415
    except ImportError as exc:
        _log_warning(
            "NSE poller unavailable (import failure); skipping",
            error=str(exc),
        )
        return None

    poller_cfg = dict(cfg)
    poller_cfg.setdefault("watchlist_symbols", settings.get("symbols", []))
    robots = RobotsChecker()
    try:
        poller = await build(poller_cfg, redis_client, robots=robots)
    except Exception as exc:  # noqa: BLE001
        _log_warning(
            "NSE poller construction failed; skipping",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return None

    if once:
        try:
            await poller.poll_once()
        except Exception as exc:  # noqa: BLE001
            _log_warning(
                "NSE poll_once failed",
                error_type=type(exc).__name__,
                error=str(exc),
            )
        return None

    return asyncio.create_task(poller.run_forever(), name="nse-feed-poller")


async def _start_user_uploads_watcher(
    cfg: dict,
    redis_client: Any,
) -> Any | None:
    """Build and start the user-upload :class:`UserUploadWatcher` (Task 5.4)."""
    try:
        from src.research.ingest.sources.user_uploads import build  # noqa: PLC0415
    except ImportError as exc:
        _log_warning(
            "User-upload watcher unavailable; skipping",
            error=str(exc),
        )
        return None

    try:
        watcher = await build(
            cfg,
            redis_client,
            user_id_resolver=_default_user_id_resolver,
        )
    except Exception as exc:  # noqa: BLE001
        _log_warning(
            "User-upload watcher construction failed; skipping",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return None

    try:
        watcher.start()
    except Exception as exc:  # noqa: BLE001
        _log_warning(
            "User-upload watcher failed to start; skipping",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return None

    return watcher


def _default_user_id_resolver(filename: str) -> Any:
    """Default user-id resolver — extract UUID from a ``{uuid}__...`` filename.

    The gateway's :meth:`ResearchService.upload_document` writes
    uploads as ``{user_id}__{SYMBOL}__{filename}``. When a watcher is
    running standalone (no gateway in the loop), this resolver
    recovers the user id from the filename prefix. Returns ``None``
    when the prefix is not a valid UUID — the watcher then skips the
    event with a structured warning.
    """
    from uuid import UUID  # noqa: PLC0415

    prefix, _, _rest = filename.partition("__")
    prefix = prefix.strip()
    if not prefix:
        return None
    try:
        return UUID(prefix)
    except (ValueError, TypeError):
        return None


# --------------------------------------------------------------------------- #
# Settings + Redis                                                            #
# --------------------------------------------------------------------------- #


def _load_settings() -> dict:
    """Load ``config/settings.yaml`` with ``${ENV_VAR}`` expansion.

    Uses :mod:`src.utils.config_loader` when available; falls back
    to an empty dict so the worker still starts on trimmed installs.
    """
    try:
        from src.utils.config_loader import load_config  # noqa: PLC0415

        return load_config() or {}
    except Exception:
        try:
            import yaml  # noqa: PLC0415

            config_path = os.environ.get("CONFIG_PATH", "config/settings.yaml")
            with open(config_path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}


def _ingest_config(settings: dict) -> dict:
    """Extract ``settings.research.ingest`` with safe defaults."""
    research = settings.get("research") or {}
    return (research.get("ingest") or {}) if isinstance(research, dict) else {}


def _sources_block(ingest_cfg: dict, name: str) -> dict:
    """Extract ``settings.research.ingest.sources.<name>`` with defaults."""
    sources = ingest_cfg.get("sources") or {}
    block = sources.get(name) or {}
    return dict(block) if isinstance(block, dict) else {}


def _resolve_redis_url(settings: dict) -> str:
    """Resolve the Redis URL from settings/env.

    Order: ``REDIS_URL`` env → ``settings.redis.url`` → host/port
    from settings → ``redis://localhost:6379``.
    """
    url = os.environ.get("REDIS_URL")
    if url:
        return url
    redis_cfg = settings.get("redis") or {}
    if isinstance(redis_cfg, dict):
        cfg_url = redis_cfg.get("url")
        if cfg_url:
            return str(cfg_url)
        host = redis_cfg.get("host", "localhost")
        port = redis_cfg.get("port", 6379)
        return f"redis://{host}:{port}"
    return "redis://localhost:6379"


async def _connect_redis(url: str) -> Any | None:
    """Return a connected ``redis.asyncio.Redis`` or ``None`` on failure."""
    try:
        import redis.asyncio as aioredis  # noqa: PLC0415
    except ImportError:
        _log_warning("redis.asyncio not installed; worker cannot start")
        return None
    try:
        client = aioredis.from_url(url, decode_responses=True)
        await client.ping()
    except Exception as exc:  # noqa: BLE001
        _log_warning(
            "redis ping failed",
            url=url,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return None
    return client


# --------------------------------------------------------------------------- #
# Signal handling + logging                                                   #
# --------------------------------------------------------------------------- #


def _install_signal_handlers(stop_event: asyncio.Event) -> None:
    """Wire ``SIGINT`` / ``SIGTERM`` to flip ``stop_event``."""
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except (NotImplementedError, RuntimeError):
            pass


def _log_info(message: str, **fields: Any) -> None:
    try:
        _logger.info(message, extra=fields)
    except TypeError:  # pragma: no cover
        _logger.info("%s %s", message, fields)


def _log_warning(message: str, **fields: Any) -> None:
    try:
        _logger.warning(message, extra=fields)
    except TypeError:  # pragma: no cover
        _logger.warning("%s %s", message, fields)


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    sys.exit(main(sys.argv[1:]))
