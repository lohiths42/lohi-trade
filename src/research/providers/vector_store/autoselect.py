"""Vector-store backend auto-selection probes (Req 2.14, design §8).

This module hosts the *boot-time* probe that drives the
``research.vector_store.backend: auto`` decision tree described in
design §8:

    res.vector_store.backend == auto ?
    │
    ├─ yes ─► probe Postgres:
    │          SELECT 1 FROM pg_extension WHERE extname='vector';
    │          │
    │          ├─ ok (+ DATABASE_URL reachable)  ─► use pgvector
    │          └─ not present OR DB unreachable ─► use chroma
    │
    └─ no  ─► honour explicit backend

:func:`probe_pgvector` is the single probe used by the ``backend: auto``
branch of :func:`src.research.providers.registry.get_vector_store`.
Task 3.2 wires it into the registry; this module only owns the probe
itself. The registry calls it once at startup and picks ``pgvector``
on ``True`` or falls back to Chroma on ``False`` (design §8).

Contract
--------
The probe runs on the boot path — before the gateway has bound its
port, and possibly before Postgres itself is up — so its single most
important guarantee is:

    **It never raises.**

Connection refusal, auth failure, a missing ``vector`` extension, a
timeout, or ``asyncpg`` not being installed all collapse to ``False``.
A ``False`` result simply means "can't use pgvector right now", and
the registry falls back to Chroma. That is the design; see the §8
decision tree above.

The query itself is tiny:

    SELECT 1 FROM pg_extension WHERE extname='vector'

``pg_extension`` is a standard Postgres catalog — any connection with
the default role can read it, so this works against managed Postgres
services (RDS, Cloud SQL, Supabase, Neon) without extra grants.

Lazy imports
------------
``asyncpg`` is imported **inside** :func:`probe_pgvector` rather than
at module top level, so this module stays importable on bare installs
that haven't pulled in ``asyncpg`` yet (Req 2.12). The registry can
therefore always ``from .vector_store import autoselect`` during
startup without guarding the import.
"""

from __future__ import annotations

import asyncio
import logging

# Use the stdlib logger directly rather than the structured project
# logger: this probe runs routinely, and every failure mode is an
# *expected* branch of the §8 decision tree (no Postgres, no
# extension, auth mismatch, …). DEBUG is the right level for
# "something the operator only cares about when diagnosing why Chroma
# was picked", and stdlib ``logging.getLogger(__name__)`` keeps the
# probe free of internal project coupling.
logger = logging.getLogger(__name__)

# Probe query lifted verbatim from design §8.
_PROBE_SQL = "SELECT 1 FROM pg_extension WHERE extname='vector'"

# Default probe timeout. Tight on purpose: this runs on the boot path
# and must not block startup if Postgres is flapping. Two seconds is
# long enough to accommodate a slow DNS lookup + TCP handshake on a
# healthy network and short enough that a dead Postgres doesn't hold
# up gateway startup appreciably.
_DEFAULT_TIMEOUT_SECONDS = 2.0


async def probe_pgvector(
    database_url: str,
    *,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
) -> bool:
    """Return ``True`` iff the target Postgres has the ``vector`` extension.

    Runs the §8 probe query against ``database_url``. ``asyncpg.connect``
    is called with its own ``timeout`` so a dead/unreachable Postgres
    unblocks quickly, and the query itself is wrapped in
    :func:`asyncio.wait_for` with the same budget so a slow catalog
    read can't hang the boot path.

    Contract
    --------
    Returns ``False`` — never raises — on any of:

    * ``asyncpg`` not installed on this process;
    * DNS failure / connection refused / network unreachable;
    * authentication failure (wrong user/password/database);
    * the ``vector`` extension not installed on the target Postgres;
    * the connect or query exceeding ``timeout_seconds``;
    * any other exception bubbling out of ``asyncpg``.

    Returns ``True`` *only* when the probe query returns at least one
    row, which means the extension is installed *and* Postgres was
    reachable *and* authentication succeeded — exactly the condition
    under which the registry is allowed to choose the pgvector
    adapter (design §8).

    A single ``DEBUG`` log line is emitted on the false branch
    carrying the exception type (no traceback): pgvector-absent is an
    expected decision-tree branch, not an error, and the log line
    exists purely to aid diagnosis when an operator wonders why
    Chroma was picked.

    Parameters
    ----------
    database_url:
        A libpq-compatible DSN (e.g. ``postgresql://user:pw@host/db``).
        Same format as the existing ``DATABASE_URL`` env var used by
        ``backend-gateway``.
    timeout_seconds:
        Wall-clock budget for both the ``asyncpg.connect`` call and
        the probe query, in seconds. The default (2.0 s) is tuned for
        the boot path; callers running this interactively (e.g. in
        tests) may want a shorter or longer value.

    """
    # Lazy import so this module stays importable on bare installs
    # (``asyncpg`` is an optional dep until the pgvector backend is
    # actually selected).
    try:
        import asyncpg  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001 - probe must never raise
        # ``ImportError`` is the common case here but we deliberately
        # catch ``Exception`` so a broken ``asyncpg`` install (bad
        # C-extension, partial wheel, …) can't bubble up either.
        logger.debug(
            "pgvector probe: asyncpg unavailable (%s); returning False",
            type(exc).__name__,
        )
        return False

    conn = None
    try:
        conn = await asyncpg.connect(database_url, timeout=timeout_seconds)
        row = await asyncio.wait_for(
            conn.fetchrow(_PROBE_SQL),
            timeout=timeout_seconds,
        )
        # ``fetchrow`` returns ``None`` when the query produces zero
        # rows, which is exactly the "extension missing" signal.
        return row is not None
    except Exception as exc:  # noqa: BLE001 - probe must never raise
        # Covers ``asyncio.TimeoutError``, ``asyncpg`` connection and
        # auth errors, Postgres-side errors, and anything else. We
        # log the exception *type* but not the traceback — under
        # normal operation this branch fires every time the service
        # is deployed without pgvector, and a stack trace would be
        # noise rather than signal.
        logger.debug(
            "pgvector probe failed (%s); returning False",
            type(exc).__name__,
        )
        return False
    finally:
        # Always close the connection if we opened one. ``close()`` is
        # an async method; swallow its errors too so a flapping
        # backend can't turn a successful probe into a raised
        # exception after the fact.
        if conn is not None:
            try:
                await conn.close()
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "pgvector probe: error closing connection (%s)",
                    type(exc).__name__,
                )


def probe_pgvector_sync(
    database_url: str,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
) -> bool:
    """Synchronous wrapper around :func:`probe_pgvector`.

    The registry boot path runs before any event loop is active on
    some deployments (e.g. a sync WSGI entry point that only starts
    the asyncio loop after config is resolved). This wrapper gives
    those callers a plain sync entry point via :func:`asyncio.run`.

    Contract when an event loop is already running
    ----------------------------------------------
    Calling :func:`asyncio.run` from inside a running loop raises
    ``RuntimeError: asyncio.run() cannot be called from a running
    event loop``. We detect that case up-front and re-raise a
    ``RuntimeError`` with a clear message directing the caller at
    the async entry point — in that context, ``await
    probe_pgvector(...)`` is the correct API and the sync wrapper
    simply cannot help. This keeps the sync wrapper "works by
    default" without silently doing something surprising (e.g.
    spinning up a worker thread just to host a second loop) when
    misused.

    Mirrors :func:`probe_pgvector` in every other respect.
    """
    # Detect a running loop *before* constructing any coroutine. This
    # avoids the ``RuntimeWarning: coroutine ... was never awaited``
    # that otherwise fires when ``asyncio.run`` rejects the call and
    # the coroutine is garbage-collected unawaited. ``get_running_loop``
    # raises ``RuntimeError`` when no loop is running, which is the
    # condition under which we want to proceed.
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop — the normal, expected entry path.
        pass
    else:
        raise RuntimeError(
            "probe_pgvector_sync() cannot be called from a running "
            "event loop; await probe_pgvector(...) directly instead.",
        )

    return asyncio.run(
        probe_pgvector(database_url, timeout_seconds=timeout_seconds),
    )


__all__ = ["probe_pgvector", "probe_pgvector_sync"]
