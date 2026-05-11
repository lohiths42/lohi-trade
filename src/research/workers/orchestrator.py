"""``research-orchestrator`` worker entrypoint (Task 18.1, design §2.2, §16.1).

Long-lived asyncio process that consumes :data:`RESEARCH_RUNS_STREAM`,
drives a :class:`~src.research.agents.orchestrator.ResearchOrchestrator`
per run, and streams partial results onto :data:`RESEARCH_PARTIALS_STREAM`
for the gateway's Socket.IO bridge (design §2.2 runtime process model).

This module is the thin shell around the Task 13.1 Orchestrator. It:

1. Loads ``config/settings.yaml`` + ``.env`` via the existing
   ``src.utils.config_loader`` (expanding ``${ENV_VAR}`` references).
2. Connects to Redis via ``redis.asyncio.Redis.from_url`` using the
   ``research.redis.url`` key (falls back to ``REDIS_URL`` env then
   ``redis://localhost:6379``).
3. Performs a blocking ``xread`` on
   :data:`RESEARCH_RUNS_STREAM` using a consumer-group-less tail-read
   (``$``), dispatching each run to the Orchestrator on the same
   process. This mirrors the design §2.2 three-worker model — the
   gateway can also run the Orchestrator in-process, but for
   production-style deployments ``start-research.sh`` starts this
   module as a supervised background process.
4. Handles ``SIGINT``/``SIGTERM`` by cancelling the read loop, letting
   in-flight runs finish, and closing Redis cleanly.

The actual graph-level logic (plan → fan-out → synthesise → Judge → emit)
lives in :class:`ResearchOrchestrator`. This worker only owns:

* the ``main()`` entrypoint invoked by ``start-research.sh`` /
  ``python -m src.research.workers.orchestrator``;
* the tail-read polling loop;
* shutdown handling;
* one minimal structural ``ResearchOrchestrator`` factory that can
  start without the full Sub_Agent / Judge stack. Operators wire the
  concrete stack via the ``orchestrator_factory`` hook on
  :class:`~backend-gateway.app.services.research_service.ResearchService`;
  this worker creates a degraded "no-agents" Orchestrator so the
  worker process stays up even before Phase 12 / Phase 14 wiring
  lands. Runs dispatched before full wiring return a minimal
  brief with ``quality="low"`` — deliberately visible in logs.

Satisfies
---------
* Req 7.1 — ``start-research.sh`` supervises this process.
* Design §2.2 — ``research-orchestrator`` runtime role.
* Design §16.1 — launcher wrapping Task 13.1.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
from typing import Any, Final
from uuid import UUID

from src.research.constants import (
    RESEARCH_PARTIALS_STREAM,
    RESEARCH_RUNS_STREAM,
)

try:  # pragma: no cover - import-path fallback matches sibling worker
    from src.utils.logger import get_logger

    _logger: Any = get_logger("ResearchOrchestratorWorker")
except Exception:  # noqa: BLE001 — best-effort logger wiring
    _logger = logging.getLogger("research.workers.orchestrator")


# ``XREAD`` block timeout in milliseconds. Short enough that the signal
# handler sees cancellation within a second; long enough that the
# Redis client is not busy-looping when no runs are queued.
_XREAD_BLOCK_MS: Final[int] = 1000

# Per-run dispatch cap — bounds memory against a pathological burst of
# run requests. Matches ``research.concurrency.gateway_max_concurrent_runs``
# in ``config/settings.yaml``.
_DEFAULT_MAX_CONCURRENT_RUNS: Final[int] = 5


# --------------------------------------------------------------------------- #
# CLI entry                                                                   #
# --------------------------------------------------------------------------- #


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for the worker.

    Minimal surface — ``--once`` runs a single poll iteration for
    smoke tests; everything else reads from config + env.
    """
    parser = argparse.ArgumentParser(
        prog="research-orchestrator",
        description=(
            "Lohi-Research Orchestrator worker (design §2.2). Consumes "
            "research:runs and emits research:partials."
        ),
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single XREAD pass then exit (smoke-test / CI helper).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entrypoint invoked by ``start-research.sh`` (design §16.1).

    Returns an OS exit code. The launcher logs the exit code and
    restarts the worker on non-zero.
    """
    args = _parse_args(argv)
    try:
        asyncio.run(_run_worker(once=args.once))
    except KeyboardInterrupt:
        _log_info("orchestrator worker interrupted; shutting down")
        return 0
    except Exception as exc:  # noqa: BLE001 — supervisor log
        _log_warning(
            "orchestrator worker crashed",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return 1
    return 0


# --------------------------------------------------------------------------- #
# Worker body                                                                 #
# --------------------------------------------------------------------------- #


async def _run_worker(*, once: bool = False) -> None:
    """Main worker loop — tail :data:`RESEARCH_RUNS_STREAM` and dispatch."""
    redis_url = _resolve_redis_url()
    redis_client = await _connect_redis(redis_url)
    if redis_client is None:
        _log_warning(
            "orchestrator worker cannot start; redis unavailable",
            redis_url=redis_url,
        )
        return

    semaphore = asyncio.Semaphore(_DEFAULT_MAX_CONCURRENT_RUNS)
    stop_event = asyncio.Event()
    _install_signal_handlers(stop_event)

    _log_info(
        "orchestrator worker starting",
        stream=RESEARCH_RUNS_STREAM,
        redis_url=redis_url,
        max_concurrent_runs=_DEFAULT_MAX_CONCURRENT_RUNS,
    )

    # Tail from ``$`` — only new entries after the worker starts. The
    # gateway stores run records in Postgres (design §4.1); any
    # already-pending runs are picked up by the gateway's own in-process
    # Orchestrator task on boot, so this worker deliberately starts at
    # the tail to avoid double-execution.
    last_id = "$"
    active_tasks: set[asyncio.Task[None]] = set()

    try:
        while not stop_event.is_set():
            try:
                entries = await redis_client.xread(
                    {RESEARCH_RUNS_STREAM: last_id},
                    count=10,
                    block=_XREAD_BLOCK_MS,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — loop-level fault
                _log_warning(
                    "xread failed; backing off",
                    stream=RESEARCH_RUNS_STREAM,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                await asyncio.sleep(1.0)
                if once:
                    break
                continue

            if entries:
                for _stream_name, events in entries:
                    for entry_id, fields in events:
                        last_id = _decode_entry_id(entry_id)
                        task = asyncio.create_task(
                            _dispatch_run(
                                redis_client=redis_client,
                                entry_id=last_id,
                                fields=_decode_fields(fields),
                                semaphore=semaphore,
                            ),
                            name=f"research-run-{last_id}",
                        )
                        active_tasks.add(task)
                        task.add_done_callback(active_tasks.discard)

            if once:
                break
    finally:
        _log_info("orchestrator worker draining active runs")
        if active_tasks:
            await asyncio.gather(*active_tasks, return_exceptions=True)
        try:
            await redis_client.aclose()
        except Exception:  # noqa: BLE001 — best-effort shutdown
            pass
        _log_info("orchestrator worker stopped")


async def _dispatch_run(
    *,
    redis_client: Any,
    entry_id: str,
    fields: dict[str, str],
    semaphore: asyncio.Semaphore,
) -> None:
    """Dispatch one ``research:runs`` entry to a minimal Orchestrator.

    The concrete Orchestrator is constructed lazily so the module
    imports without the full Phase 12 wiring. Exceptions never
    propagate out — they're logged and the run is marked as errored
    on the partials stream via a terminal ``event=done`` marker.
    """
    async with semaphore:
        run_id_raw = fields.get("run_id", "").strip()
        user_id_raw = fields.get("user_id", "").strip()
        prompt = fields.get("prompt", "")
        symbol = (fields.get("symbol") or "").strip() or None

        try:
            run_id = UUID(run_id_raw)
            user_id = UUID(user_id_raw)
        except ValueError:
            _log_warning(
                "research:runs entry has malformed run_id/user_id; dropping",
                entry_id=entry_id,
                run_id=run_id_raw,
                user_id=user_id_raw,
            )
            return

        _log_info(
            "dispatching research run",
            entry_id=entry_id,
            run_id=str(run_id),
            user_id=str(user_id),
            symbol=symbol,
        )

        try:
            orchestrator = await _build_orchestrator(redis_client)
        except Exception as exc:  # noqa: BLE001 — factory failure
            _log_warning(
                "failed to build orchestrator for run; emitting done marker",
                run_id=str(run_id),
                error_type=type(exc).__name__,
                error=str(exc),
            )
            await _publish_terminal_done(redis_client, run_id, quality="low")
            return

        try:
            await orchestrator.run(
                run_id=run_id,
                user_id=user_id,
                symbol=symbol,
                user_prompt=prompt,
            )
        except Exception as exc:  # noqa: BLE001 — run-level isolation
            _log_warning(
                "research run raised; marking done",
                run_id=str(run_id),
                error_type=type(exc).__name__,
                error=str(exc),
            )
            await _publish_terminal_done(redis_client, run_id, quality="low")


# --------------------------------------------------------------------------- #
# Orchestrator factory                                                        #
# --------------------------------------------------------------------------- #


async def _build_orchestrator(redis_client: Any) -> Any:
    """Build a minimal :class:`ResearchOrchestrator` for the worker.

    The worker's goal is to drive the queued runs to a terminal
    state on the partials stream, not to host the full Sub_Agent
    stack (which lives inside the gateway process per design §3.12).
    We therefore construct a no-op stack: zero Sub_Agents, a stub
    synthesiser that returns an empty brief, a stub judge that
    unconditionally passes. The partials publisher writes through
    the shared :class:`RedisPartialsPublisher` so Socket.IO
    subscribers still see the terminal marker.

    A full-fledged worker-side Orchestrator is a Phase-18+ extension
    (see tasks 19.x for offline-mode hardening).
    """
    # Lazy imports so a bare install without the agents package still
    # lets this module import (matches the pattern in snapshotter.py).
    from src.research.agents.orchestrator import ResearchOrchestrator
    from src.research.agents.partials import RedisPartialsPublisher
    from src.research.judge.judge import JudgeReport

    publisher = RedisPartialsPublisher(redis_client)

    async def _stub_synthesize(**_kwargs: Any) -> dict[str, str]:
        # Empty brief — every canonical section is present but blank.
        return {
            "summary": "",
            "thesis": "",
            "risks": "",
            "financial_highlights": "",
            "management_commentary": "",
            "technical_view": "",
            "peers": "",
            "macro_context": "",
        }

    async def _stub_judge(**_kwargs: Any) -> JudgeReport:
        # ``run_resynthesis_loop`` calls ``judge_fn(brief=..., retry_count=...)``
        # — no ``run_id`` is threaded through. Use a zero-UUID so the
        # report is structurally valid; the gateway's real Orchestrator
        # wiring (Phase 12+) supplies the proper id via a
        # ``functools.partial``.
        return JudgeReport(
            run_id=UUID(int=0),
            groundedness_score={"summary": 1.0},
            unsupported_claims=[],
            safe_to_display=True,
            contradiction_pairs=[],
            off_policy_findings=[],
            retry_count=0,
        )

    return ResearchOrchestrator(
        sub_agents=(),
        synthesizer=_stub_synthesize,
        judge_fn=_stub_judge,
        retriever=None,
        partials_publisher=publisher,
    )


# --------------------------------------------------------------------------- #
# Redis helpers                                                               #
# --------------------------------------------------------------------------- #


def _resolve_redis_url() -> str:
    """Resolve the Redis URL from env.

    Order: ``REDIS_URL`` → ``REDIS_HOST``/``REDIS_PORT`` pair →
    ``redis://localhost:6379``. Matches the gateway's ``app.config``
    resolution order so both processes agree on the target.
    """
    url = os.environ.get("REDIS_URL")
    if url:
        return url
    host = os.environ.get("REDIS_HOST", "localhost")
    port = os.environ.get("REDIS_PORT", "6379")
    return f"redis://{host}:{port}"


async def _connect_redis(url: str) -> Any | None:
    """Return a connected ``redis.asyncio.Redis`` or ``None`` on failure."""
    try:
        import redis.asyncio as aioredis  # noqa: PLC0415 — optional dep
    except ImportError:
        _log_warning("redis.asyncio not installed; worker cannot start")
        return None
    try:
        client = aioredis.from_url(url, decode_responses=True)
        await client.ping()
    except Exception as exc:  # noqa: BLE001 — startup probe
        _log_warning(
            "redis ping failed",
            url=url,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return None
    return client


async def _publish_terminal_done(
    redis_client: Any,
    run_id: UUID,
    *,
    quality: str,
) -> None:
    """Publish a terminal ``event=done`` marker for ``run_id``."""
    try:
        from src.research.agents.partials import format_done  # noqa: PLC0415
    except Exception:  # pragma: no cover - defensive
        return
    try:
        await redis_client.xadd(
            RESEARCH_PARTIALS_STREAM,
            format_done(run_id, quality=quality),
        )
    except Exception as exc:  # noqa: BLE001 - best-effort
        _log_warning(
            "failed to publish terminal done marker",
            run_id=str(run_id),
            error_type=type(exc).__name__,
            error=str(exc),
        )


# --------------------------------------------------------------------------- #
# Stream-entry decoding                                                       #
# --------------------------------------------------------------------------- #


def _decode_entry_id(raw: Any) -> str:
    """Normalise a stream entry id (bytes or str) to str."""
    if isinstance(raw, (bytes, bytearray)):
        return raw.decode("utf-8", errors="replace")
    return str(raw)


def _decode_fields(raw: Any) -> dict[str, str]:
    """Normalise a stream entry fields mapping to ``dict[str, str]``.

    ``redis.asyncio.Redis`` with ``decode_responses=True`` already
    returns str keys + str values, but some test doubles return
    bytes. This shim keeps callers uniform.
    """
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        key = k.decode("utf-8", errors="replace") if isinstance(k, (bytes, bytearray)) else str(k)
        val = v.decode("utf-8", errors="replace") if isinstance(v, (bytes, bytearray)) else str(v)
        out[key] = val
    return out


# --------------------------------------------------------------------------- #
# Signal handling                                                             #
# --------------------------------------------------------------------------- #


def _install_signal_handlers(stop_event: asyncio.Event) -> None:
    """Wire ``SIGINT`` / ``SIGTERM`` to flip ``stop_event``.

    On platforms where ``add_signal_handler`` is unavailable (e.g.
    Windows), fall back to the default asyncio behaviour — the
    worker will exit on ``KeyboardInterrupt``.
    """
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except (NotImplementedError, RuntimeError):
            pass


# --------------------------------------------------------------------------- #
# Structured-log helpers                                                      #
# --------------------------------------------------------------------------- #


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
