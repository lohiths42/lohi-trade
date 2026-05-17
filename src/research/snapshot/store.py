"""Snapshot persistence — ``research_snapshots`` writer/reader (Task 15.3).

Persists the per-``(user_id, symbol)`` :class:`Snapshot` rows that the
``research-snapshotter`` worker produces (design §3.10) and serves
fresh rows back to the Orchestrator so a fresh Snapshot short-circuits
the Sub_Agent fan-out (Req 5.5, design §13.3).

Role in the subsystem
---------------------
The snapshot lifecycle has three moving parts, each mapped to one
method on :class:`SnapshotStore`:

* :meth:`save_snapshot` — called by the snapshotter worker after a
  successful regeneration. Upserts a row carrying ``brief_json``,
  ``generated_at`` (set to ``now()``), the sorted
  ``input_document_hashes`` list, and ``stale=false``. Replacing the
  row clears any previous ``stale=true`` marker from an earlier
  failure — a successful regen always wins.
* :meth:`mark_stale` — called by the snapshotter worker when a
  regeneration attempt fails. The previous row is retained verbatim;
  we only flip ``stale=true`` so the UI can render a staleness badge
  (Req 11.6). Absent rows are a no-op: there is no "stale empty"
  state — a user with no snapshot yet will simply fall through to the
  full fan-out path.
* :meth:`get_fresh_snapshot` — called by the gateway's Research_Run
  path (future Task 16.1 wiring). Returns the stored brief if the row
  exists, is not ``stale``, and was generated within the configured
  staleness window (Req 11.4, design §13.3 default 15 minutes).
  Returns ``None`` in every other case so the caller can proceed to
  the full fan-out without a special error type.

RLS engagement
--------------
Every method routes through the injected ``connection_factory`` — the
same pattern :mod:`src.research.agents.usage_writer` and
:mod:`src.research.memory.semantic` use. The factory is a callable
``(user_id) -> AsyncContextManager[asyncpg.Connection]`` that yields a
connection with ``app.user_id`` already set for the transaction, so
the RLS policy on ``research_snapshots`` (design §4.1) authorises the
INSERT/UPDATE/SELECT against the right tenant without an explicit
``WHERE user_id = $1`` on every statement.

Satisfies
---------
* **Req 5.5** — a fresh Snapshot short-circuits the Sub_Agent fan-out.
* **Req 11.4** — staleness window (default 900s = 15 min) applied to
  the ``generated_at`` timestamp.
* **Req 11.5** — stored row carries ``generated_at`` and
  ``input_document_hashes``.
* **Req 11.6** — regeneration failure path retains the previous row
  and flips ``stale=true``.
* Design §3.10 — per-``(user_id, symbol)`` Snapshot cache.
* Design §13.3 — Snapshot table schema + staleness semantics.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

if TYPE_CHECKING:  # pragma: no cover - typing only
    from contextlib import AbstractAsyncContextManager

    import asyncpg


# ``src.utils.logger`` provides the project-standard structured
# logger; fall back to stdlib ``logging`` on trimmed installs. Same
# pattern every :mod:`src.research` module uses.
try:  # pragma: no cover - import-path fallback
    from src.utils.logger import get_logger

    _logger: Any = get_logger("SnapshotStore")
except Exception:  # noqa: BLE001 - best-effort logger wiring
    import logging

    _logger = logging.getLogger("research.snapshot.store")


__all__ = [
    "DEFAULT_STALENESS_WINDOW_SEC",
    "SnapshotRecord",
    "SnapshotStore",
]


# Default staleness window (design §13.3, Req 11.4 "default 15 minutes").
# Matches ``research.snapshot.staleness_window_sec`` in
# ``config/settings.yaml`` (design §7.1).
DEFAULT_STALENESS_WINDOW_SEC: Final[int] = 900


class SnapshotRecord:
    """Lightweight view over a ``research_snapshots`` row.

    Returned by :meth:`SnapshotStore.get_fresh_snapshot` so callers see
    the same five fields regardless of which asyncpg row type the
    driver happened to hand back. Kept as a plain class (not a
    :func:`dataclasses.dataclass`) so it has no dependency footprint
    beyond the Python stdlib — the ``ResearchBrief`` Pydantic model
    (design §4.2) is the authoritative shape for the contained
    ``brief``; this record is just a transport envelope.
    """

    __slots__ = (
        "brief",
        "generated_at",
        "input_document_hashes",
        "stale",
        "symbol",
        "user_id",
    )

    def __init__(
        self,
        *,
        user_id: UUID,
        symbol: str,
        brief: Mapping[str, Any],
        generated_at: datetime,
        input_document_hashes: list[str],
        stale: bool,
    ) -> None:
        self.user_id = user_id
        self.symbol = symbol
        self.brief = dict(brief)
        self.generated_at = generated_at
        self.input_document_hashes = list(input_document_hashes)
        self.stale = stale

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"SnapshotRecord(user_id={self.user_id!r}, symbol={self.symbol!r}, "
            f"generated_at={self.generated_at!r}, stale={self.stale!r}, "
            f"hashes={len(self.input_document_hashes)})"
        )


class SnapshotStore:
    """CRUD over ``research_snapshots`` with RLS engaged per call.

    Parameters
    ----------
    connection_factory:
        Callable ``(user_id) -> AsyncContextManager[asyncpg.Connection]``.
        Every method invokes it with the operation's ``user_id`` so the
        underlying transaction has ``app.user_id`` set for the duration
        — the RLS policy then both scopes reads and authorises
        INSERT/UPDATE against the same tenant (design §4.1, §14).
    clock:
        Optional callable returning the "now" :class:`datetime` used
        for the freshness comparison. Defaults to
        ``lambda: datetime.now(timezone.utc)``. Exposed so unit tests
        can pin time without monkey-patching module state.

    """

    # Columns in the migration order (design §4.1):
    #   user_id, symbol, brief_json, generated_at, input_document_hashes, stale
    #
    # On an upserting regen, we replace every column so a previous
    # ``stale=true`` flag cannot linger. ``ON CONFLICT (user_id, symbol)``
    # matches the composite primary key declared in the migration.
    _UPSERT_SQL: Final[str] = (
        "INSERT INTO research_snapshots "
        "(user_id, symbol, brief_json, generated_at, "
        "input_document_hashes, stale) "
        "VALUES ($1, $2, $3::jsonb, $4, $5, $6) "
        "ON CONFLICT (user_id, symbol) DO UPDATE SET "
        "brief_json = EXCLUDED.brief_json, "
        "generated_at = EXCLUDED.generated_at, "
        "input_document_hashes = EXCLUDED.input_document_hashes, "
        "stale = EXCLUDED.stale"
    )

    # ``mark_stale`` touches only the ``stale`` column so a downstream
    # reader can still see the previous ``brief_json`` /
    # ``generated_at`` values (Req 11.6). Returns the count of rows
    # affected via asyncpg's command tag so the caller can distinguish
    # "flipped" from "no row yet".
    _MARK_STALE_SQL: Final[str] = (
        "UPDATE research_snapshots SET stale = TRUE " "WHERE user_id = $1 AND symbol = $2"
    )

    _SELECT_SQL: Final[str] = (
        "SELECT user_id, symbol, brief_json, generated_at, "
        "input_document_hashes, stale "
        "FROM research_snapshots "
        "WHERE user_id = $1 AND symbol = $2"
    )

    def __init__(
        self,
        *,
        connection_factory: Callable[
            [UUID],
            AbstractAsyncContextManager[asyncpg.Connection],
        ],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._conn_factory = connection_factory
        self._clock = clock or _default_clock

    # ------------------------------------------------------------------ #
    # Writes                                                             #
    # ------------------------------------------------------------------ #

    async def save_snapshot(
        self,
        user_id: UUID,
        symbol: str,
        brief: Mapping[str, Any],
        input_document_hashes: list[str] | tuple[str, ...],
        *,
        generated_at: datetime | None = None,
    ) -> None:
        """Upsert a fresh Snapshot, clearing any prior ``stale=true``.

        ``generated_at`` defaults to ``self._clock()`` — tests that
        want to pin the timestamp pass an explicit value. The
        persisted ``input_document_hashes`` is sorted so re-generations
        over the same corpus produce identical rows regardless of the
        order the caller passed hashes in.

        Requirements: 11.1, 11.2, 11.5
        Design: §3.10, §4.1
        """
        sym = _normalise_symbol(symbol)
        hashes = sorted(h for h in input_document_hashes if h)
        generated_at_ts = generated_at or self._clock()
        brief_json = _encode_brief(brief)

        async with self._conn_factory(user_id) as conn:
            await conn.execute(
                self._UPSERT_SQL,
                user_id,
                sym,
                brief_json,
                generated_at_ts,
                hashes,
                False,
            )

        _log_debug(
            "snapshot upsert ok",
            user_id=str(user_id),
            symbol=sym,
            hashes=len(hashes),
            generated_at=generated_at_ts.isoformat(),
        )

    async def mark_stale(self, user_id: UUID, symbol: str) -> bool:
        """Flip ``stale=true`` on the existing row; no-op when absent.

        Returns ``True`` when an existing row was flipped, ``False``
        when no row matched. Callers can use this to log a warning
        when they expected a row to be present but the table was
        empty — the snapshotter worker does this when a regen
        fails before any successful run has ever written a row.

        Requirements: 11.6
        Design: §3.10
        """
        sym = _normalise_symbol(symbol)

        async with self._conn_factory(user_id) as conn:
            command_tag = await conn.execute(self._MARK_STALE_SQL, user_id, sym)

        affected = _parse_update_count(command_tag)
        _log_debug(
            "snapshot mark_stale",
            user_id=str(user_id),
            symbol=sym,
            affected=affected,
        )
        return affected > 0

    # ------------------------------------------------------------------ #
    # Reads                                                              #
    # ------------------------------------------------------------------ #

    async def get_fresh_snapshot(
        self,
        user_id: UUID,
        symbol: str,
        staleness_window_sec: int = DEFAULT_STALENESS_WINDOW_SEC,
    ) -> SnapshotRecord | None:
        """Return the stored brief when fresh, else ``None``.

        "Fresh" means three conditions hold together:

        1. A row exists for ``(user_id, symbol)``.
        2. ``stale`` is ``False``.
        3. ``now() - generated_at <= staleness_window_sec``.

        The staleness comparison is done in the store (not in SQL) so
        a test-supplied :attr:`_clock` can deterministically drive the
        freshness decision without a round-trip to the database.

        A non-positive ``staleness_window_sec`` is treated as "never
        fresh": the method short-circuits to ``None`` even when a row
        exists. This matches the intent of an operator who wants to
        force every run through the fan-out path (e.g. to debug a
        regen).

        Requirements: 5.5, 11.4
        Design: §3.10, §13.3
        """
        if staleness_window_sec <= 0:
            return None

        sym = _normalise_symbol(symbol)

        async with self._conn_factory(user_id) as conn:
            row = await conn.fetchrow(self._SELECT_SQL, user_id, sym)

        if row is None:
            return None

        stale = bool(row["stale"])
        if stale:
            return None

        generated_at: datetime = row["generated_at"]
        now = self._clock()
        # ``generated_at`` comes out of Postgres with ``tzinfo`` set
        # because the column type is ``TIMESTAMPTZ``; normalise both
        # sides to UTC-aware datetimes so naive test clocks don't
        # trip an awareness mismatch.
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)

        age_sec = (now - generated_at).total_seconds()
        if age_sec < 0:
            # ``generated_at`` is in the future — treat as fresh. This
            # can happen in test fixtures that pin ``generated_at`` at
            # ``now + delta`` to simulate race conditions; returning
            # the row preserves "the most recent row wins" without a
            # clock-skew failure mode.
            age_sec = 0.0
        if age_sec > staleness_window_sec:
            return None

        return SnapshotRecord(
            user_id=row["user_id"],
            symbol=row["symbol"],
            brief=_decode_brief(row["brief_json"]),
            generated_at=generated_at,
            input_document_hashes=list(row["input_document_hashes"] or []),
            stale=stale,
        )


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _default_clock() -> datetime:
    """UTC-aware "now" used by :class:`SnapshotStore` by default."""
    return datetime.now(UTC)


def _normalise_symbol(symbol: str) -> str:
    """Upper-case and strip a ticker.

    Every upstream publisher already emits upper-case Indian-market
    tickers, but the snapshotter consumes bias events whose casing
    cannot be trusted across test fixtures. Normalising once here
    keeps ``(user_id, symbol)`` primary-key lookups deterministic.
    """
    return symbol.strip().upper()


def _encode_brief(brief: Mapping[str, Any]) -> str:
    """JSON-dump the brief for the ``brief_json::jsonb`` bind.

    asyncpg accepts a Python ``str`` for a ``jsonb`` parameter when
    the cast is explicit in the SQL (``$3::jsonb`` above). Using
    ``json.dumps`` rather than passing the dict directly avoids an
    asyncpg version dependency on the ``jsonb`` codec registration
    done elsewhere in the gateway.
    """
    return json.dumps(brief, ensure_ascii=False, separators=(",", ":"))


def _decode_brief(value: Any) -> dict[str, Any]:
    """Decode a ``brief_json`` column back into a plain dict.

    asyncpg returns ``jsonb`` as a ``str`` by default; some wiring
    layers (or tests) may hand back a dict already. Accept both so
    the store stays robust to codec-registration drift.
    """
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, (bytes, bytearray)):
        return json.loads(value.decode("utf-8"))
    if isinstance(value, str):
        return json.loads(value)
    # Unknown shape — return an empty dict so callers don't crash on
    # a driver hiccup; the Orchestrator treats "empty brief" as
    # "no_data" and will fall through to the fan-out path.
    return {}


def _parse_update_count(command_tag: Any) -> int:
    """Extract the row count from an asyncpg ``UPDATE N`` command tag.

    Mirrors :func:`src.research.memory.semantic._parse_delete_count`
    but for UPDATE. A non-UPDATE or malformed tag collapses to 0 so
    a driver oddity does not break the "no row present" branch in
    :meth:`SnapshotStore.mark_stale`.
    """
    if not isinstance(command_tag, str):
        return 0
    parts = command_tag.strip().split()
    if len(parts) >= 2 and parts[0].upper() == "UPDATE":
        try:
            return int(parts[1])
        except ValueError:
            return 0
    return 0


def _log_debug(message: str, **fields: Any) -> None:
    """Emit a DEBUG log, adapting to the available logger shape."""
    try:
        _logger.debug(message, extra=fields)
    except TypeError:  # pragma: no cover - very old logger variants
        _logger.debug("%s %s", message, fields)
