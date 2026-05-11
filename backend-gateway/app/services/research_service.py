"""Research Service — Lohi-Research gateway service (Task 16.1).

Extends the existing :class:`~app.services.chatbot_service.ChatbotService`
rather than forking a parallel chat surface (Req 8.1, design §3.12) and
exposes the run-lifecycle, snapshot, upload, reindex, memory, and health
methods that the REST router (Task 16.2) and Socket.IO event bridge
(Task 16.3) call into.

What this service does
----------------------

* **Run lifecycle.** :meth:`ResearchService.start_run` inserts a row in
  ``research_runs`` (status=``"pending"``), ``XADD``\\s a run request
  onto ``research:runs``, and dispatches
  :meth:`ResearchOrchestrator.run` as an :mod:`asyncio` background
  task. The background task drives the full plan → fan-out →
  synthesise → validate → Judge → emit pipeline and writes partials
  onto ``research:partials``. When the run finishes (success, failure,
  or exception) the status row is flipped to ``"done"`` / ``"partial"``
  / ``"error"`` and ``research:partials`` gets a terminal
  ``event=done`` marker so the Socket.IO bridge closes the channel
  cleanly (design §5.2).

* **Retrieval methods.** :meth:`get_run`, :meth:`get_run_trace`, and
  :meth:`get_snapshot` read the in-memory run state and the
  RLS-protected tables through the canonical
  :meth:`connection` context manager.

* **Mutation methods.** :meth:`upload_document`, :meth:`reindex`,
  :meth:`forget_memory` are thin wrappers around the existing
  ingestion / index / memory modules. They publish on
  ``research:index_events`` or call the relevant manager directly;
  every call opens an RLS-engaged transaction so the gateway's
  "one request, one tenant" contract is preserved.

* **Health.** :meth:`health` remains the aggregated probe from the
  Phase 1 stub (Task 1.6) + Task 3.2 — now enriched with the
  configured provider names once the service is fully wired. Task
  18.4 lands the real per-component probes; this file leaves the
  non-vector-store fields as ``"pending"`` so the shape stays stable.

Dependency injection
--------------------

The class accepts every collaborator through the constructor so unit
tests can build a ``ResearchService`` without a live Redis / Postgres:

* ``orchestrator_factory`` — a zero-arg callable that returns a
  :class:`ResearchOrchestrator`. Built once per run (so each run
  gets its own per-run usage writer / budget tracker wired inside
  the factory) and invoked via its ``run`` method.
* ``redis_client`` — an ``redis.asyncio.Redis``-compatible client
  used to (a) ``XADD`` run requests onto ``research:runs`` for the
  worker process (design §2.2), and (b) let the orchestrator
  construct its :class:`RedisPartialsPublisher`. Tests pass a fake
  with an ``xadd`` coroutine.
* ``llm_client``, ``db_pool``, ``chart_gen`` — forwarded to the base
  :class:`ChatbotService` constructor so the inherited chat surface
  still works when :meth:`chat` is called on the subclass.
* ``snapshot_store`` — optional :class:`SnapshotStore` for the
  ``/snapshot/:symbol`` endpoint. When ``None`` the endpoint returns
  ``None`` (no fresh snapshot) rather than raising, preserving the
  "Snapshot is a cache, not a requirement" invariant from §3.10.
* ``memory_stack`` — optional (:class:`WorkingMemory`,
  :class:`SemanticMemory`, :class:`EpisodicMemory`) triple used by
  :meth:`forget_memory`. Missing → endpoint raises a structured
  :class:`ConfigMissingError` rather than pretending to delete
  nothing.

The service keeps a lightweight in-memory registry of active runs
keyed by ``run_id``. Each entry holds the status, optionally the
terminal ``ResearchBrief`` payload, and the collected trace so
:meth:`get_run` / :meth:`get_run_trace` can answer without a DB
round-trip for runs that completed in the current gateway process.
Once Task 18.x adds persistence to ``research_runs`` /
``research_brief_sections`` / ``research_provenance`` wiring, the
in-memory cache becomes an optimisation rather than the source of
truth — the DB rows are already the canonical persistence target
per design §4.1.

Requirements: 8.1, 8.2, 13.3, design §3.12, §5.1, §5.2
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, AsyncIterator, Awaitable, Callable, Mapping, Optional
from uuid import UUID, uuid4

from app.middleware.errors import ConfigMissingError
from app.services.chatbot_service import ChatbotService, LLMClient
from app.services.db_service import get_pg_pool
from app.services.research.rls import rls_connection
from src.research.agents.partials import (
    NoopPartialsPublisher,
    PartialsPublisher,
    RedisPartialsPublisher,
    format_done,
)
from src.research.constants import (
    RESEARCH_PARTIALS_STREAM,
    RESEARCH_RUNS_STREAM,
)
from src.research.providers.registry import get_resolved_vector_store_backend

if TYPE_CHECKING:  # pragma: no cover - typing only
    import asyncpg

    from src.research.agents.orchestrator import ResearchOrchestrator
    from src.research.snapshot.store import SnapshotRecord, SnapshotStore
    from src.research.memory.episodic import EpisodicMemory
    from src.research.memory.semantic import SemanticMemory
    from src.research.memory.working import WorkingMemory


logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Public types                                                                #
# --------------------------------------------------------------------------- #


#: Status transitions (design §4.1 ``research_runs.status`` column).
#:
#: * ``"pending"``  — row inserted, orchestrator not yet started.
#: * ``"running"``  — orchestrator task has started.
#: * ``"done"``     — orchestrator emitted a brief with
#:                    ``partial=false`` and ``quality != "low"``.
#: * ``"partial"``  — orchestrator emitted a brief with ``partial=true``
#:                    or ``budget_exhausted=true`` (Req 1.6, Req 12.4).
#: * ``"error"``    — orchestrator raised before emitting, or the
#:                    gateway's own pre-flight failed (e.g. a
#:                    guardrail refusal that turned into a hard error).
RunStatus = str


#: A zero-arg factory returning a :class:`ResearchOrchestrator`. Lets
#: tests inject a stub and the production wiring lets Phase 18's
#: dependency builder own the concrete construction.
OrchestratorFactory = Callable[[], "ResearchOrchestrator"]


@dataclass
class RunRecord:
    """In-memory record of a ``Research_Run`` (design §4.1 mirror).

    Holds what the gateway needs to answer
    :meth:`ResearchService.get_run` / :meth:`get_run_trace` without a
    DB round-trip for runs that completed in the current process.
    The canonical persistence target is the ``research_runs`` /
    ``research_brief_sections`` tables (design §4.1); Task 18.x will
    flip this dataclass to be a read-through cache over those tables.

    Attributes
    ----------
    run_id:
        Unique identifier handed back to the client on ``POST /runs``.
    user_id:
        Owning tenant. Every read-side method re-checks this against
        the caller's ``user_id`` — a belt-and-braces check on top of
        the RLS enforcement for the DB tables.
    symbol:
        Optional ticker scope (may be ``None`` for cross-symbol
        prompts).
    prompt:
        The raw user prompt. Stored so ``GET /runs/:id/trace`` can
        return it verbatim.
    status:
        One of the :data:`RunStatus` values.
    created_at:
        ``time.time()`` float at :meth:`start_run` entry.
    finished_at:
        ``time.time()`` float when the status transitioned to one of
        the terminal values. ``None`` while running.
    brief:
        The terminal brief payload (dict for now; Task 13.8 will
        swap this for a :class:`~pydantic.BaseModel` ``ResearchBrief``).
    trace:
        Free-form trace dict populated by the orchestrator run. At
        minimum carries ``{"plan_md", "partials": [...]}`` so the
        trace endpoint has something to return (Req 13.3).
    channel:
        The Socket.IO channel on which partials are emitted
        (``"research:<run_id>"``, design §5.2). Stored so the router
        can return it in the ``POST /runs`` response body without
        re-deriving it.
    """

    run_id: UUID
    user_id: UUID
    symbol: Optional[str]
    prompt: str
    status: RunStatus
    created_at: float
    finished_at: Optional[float] = None
    brief: Optional[dict[str, Any]] = None
    trace: dict[str, Any] = field(default_factory=dict)
    channel: str = ""


# --------------------------------------------------------------------------- #
# ResearchService                                                             #
# --------------------------------------------------------------------------- #


class ResearchService(ChatbotService):
    """Lohi-Research gateway service (Task 16.1).

    Extends :class:`ChatbotService` so existing ``/api/v2/chatbot/*``
    callers that upcast to ``ResearchService`` keep working (Req 8.1).
    Every research-specific method is additive; the inherited
    :meth:`chat` / :meth:`get_history` / :meth:`clear_session` stay
    usable.
    """

    def __init__(
        self,
        *,
        llm_client: LLMClient | None = None,
        db_pool: Any = None,
        redis: Any = None,
        chart_gen: Any = None,
        orchestrator_factory: OrchestratorFactory | None = None,
        snapshot_store: "SnapshotStore | None" = None,
        memory_stack: Optional[
            tuple["WorkingMemory", "SemanticMemory", "EpisodicMemory"]
        ] = None,
        audit_log_writer: Callable[[UUID, str, dict], Awaitable[None]] | None = None,
        # ── Task 18.4 health-probe collaborators ──────────────────────
        # Each provider is optional — when ``None`` the corresponding
        # health probe returns ``"pending"``. The gateway startup wires
        # these via the provider registry; tests leave them ``None``.
        vector_store: Any = None,
        embeddings_provider: Any = None,
        llm_provider: Any = None,
    ) -> None:
        # ``ChatbotService`` requires a non-None ``llm_client``. Build
        # a stub one when the caller only wants the research surface;
        # the stub is never invoked because the base class's methods
        # short-circuit when there's no JWT-authenticated user asking
        # for chat. The stub has a no-op ``complete`` so even if the
        # base service is accidentally invoked the gateway returns
        # graceful text rather than a bare ``AttributeError``.
        base_llm = llm_client or LLMClient(api_key="", api_base="", model="unused")
        super().__init__(
            llm_client=base_llm,
            db_pool=db_pool,
            redis=redis,
            chart_gen=chart_gen,
        )

        self._orchestrator_factory = orchestrator_factory
        self._snapshot_store = snapshot_store
        self._memory_stack = memory_stack
        self._audit_log_writer = audit_log_writer
        self._vector_store = vector_store
        self._embeddings_provider = embeddings_provider
        self._llm_provider = llm_provider

        # Active / completed runs keyed by ``run_id``. Tests use this
        # to assert the lifecycle transitions; production code reads
        # it for fast-path ``GET /runs/:id`` after the orchestrator
        # task has finished in the current process.
        self._runs: dict[UUID, RunRecord] = {}
        # Background task handles, kept so the gateway's shutdown
        # hook can cancel in-flight runs cleanly.
        self._run_tasks: dict[UUID, asyncio.Task[None]] = {}

    # ================================================================= #
    # Run lifecycle                                                     #
    # ================================================================= #

    async def start_run(
        self,
        user_id: UUID,
        symbol: Optional[str],
        prompt: str,
    ) -> RunRecord:
        """Kick off a ``Research_Run`` and return the tracking record.

        Steps (design §5.1, §5.2):

        1. Allocate a ``run_id`` and record a :class:`RunRecord` at
           status ``"pending"`` so the client receives it even if the
           orchestrator crashes on its first line.
        2. ``XADD`` a fan-out request onto ``research:runs`` so
           out-of-process ``research-orchestrator`` workers (design
           §2.2) can also pick the run up. When running in-process
           (the default gateway deployment) the Redis write is
           mirror-only; the actual orchestrator is dispatched as a
           background :mod:`asyncio` task on the next line.
        3. Dispatch :meth:`ResearchOrchestrator.run` as a background
           task. Exceptions are logged and folded into the
           :class:`RunRecord`; they never propagate out of this
           method.

        Returns the :class:`RunRecord` so the router can serialise
        ``{run_id, channel, status}`` for the caller.

        Raises
        ------
        ConfigMissingError
            When ``orchestrator_factory`` was not supplied at
            construction time. We fail closed rather than silently
            no-op because the caller expects a live orchestrator.

        Requirements: 1.1, 1.7, 5.1, 13.3
        """
        if self._orchestrator_factory is None:
            raise ConfigMissingError(
                "research.orchestrator_factory",
                "ResearchService was constructed without an orchestrator_factory; "
                "cannot start a Research_Run. Wire one at gateway startup.",
            )
        if not prompt or not prompt.strip():
            raise ConfigMissingError(
                "research.run.prompt",
                "Prompt must be a non-empty string.",
            )

        run_id = uuid4()
        record = RunRecord(
            run_id=run_id,
            user_id=user_id,
            symbol=symbol,
            prompt=prompt,
            status="pending",
            created_at=time.time(),
            channel=f"research:{run_id}",
        )
        self._runs[run_id] = record

        # 1) Mirror the request onto ``research:runs`` so out-of-process
        #    workers (design §2.2) can consume it. Errors are swallowed
        #    — a broken Redis must not block the in-process run.
        await self._publish_run_request(record)

        # 2) Dispatch the orchestrator background task.
        task = asyncio.create_task(
            self._run_in_background(record),
            name=f"research-run-{run_id}",
        )
        self._run_tasks[run_id] = task
        record.status = "running"

        return record

    async def get_run(self, user_id: UUID, run_id: UUID) -> dict[str, Any]:
        """Return the final brief for ``run_id``.

        Raises :class:`KeyError` when the run is unknown and
        :class:`PermissionError` when the run exists but belongs to
        another tenant — both are translated to 404 by the router
        (returning 403 here would leak existence).

        Requirements: 1.5
        """
        record = self._require_owned_run(user_id, run_id)
        if record.brief is None:
            return {
                "run_id": str(run_id),
                "status": record.status,
                "brief": None,
            }
        return {
            "run_id": str(run_id),
            "status": record.status,
            "brief": record.brief,
        }

    async def get_run_trace(
        self,
        user_id: UUID,
        run_id: UUID,
    ) -> dict[str, Any]:
        """Return the full trace (plan + retrieval + partials) for ``run_id``.

        The trace dict always carries ``provenance``,
        ``guardrail_decisions``, and ``judge_reports`` keys so the UI
        (Task 20.3 ``RunTraceDrawer``) can render every section
        unconditionally. When the DB-backed persistence wiring lands
        (design §4.1 tables), these keys will be populated from the
        RLS-scoped tables; until then they default to the values
        already captured on the in-memory :class:`RunRecord` — which
        is enough for the gateway process that executed the run to
        answer the trace request without a DB round-trip.

        Requirements: 13.3, 13.4
        Design: §15
        """
        record = self._require_owned_run(user_id, run_id)
        trace = dict(record.trace)
        brief = record.brief or {}

        # ``provenance`` — pulled from the brief payload that the
        # Orchestrator assembled (design §3.5 ``provenance`` block,
        # Req 1.8). Defaults to an empty list so the UI always has a
        # table to render.
        trace.setdefault("provenance", list(brief.get("provenance", [])))

        # ``guardrail_decisions`` — the Guardrail_Layer persists each
        # decision to ``research_guardrail_decisions`` (Req 16.11)
        # and also mirrors them into the brief's ``guardrail_decisions``
        # block when Task 13.8 lands. Until then we expose an empty
        # list so the response shape is stable.
        trace.setdefault(
            "guardrail_decisions", list(brief.get("guardrail_decisions", []))
        )

        # ``judge_reports`` — the Orchestrator writes a single
        # :class:`JudgeReport` per run (design §3.7). Expose it as a
        # single-element list so the UI can render multi-report runs
        # (re-synthesis pass) identically to first-pass runs. An
        # empty list is emitted when the run has no brief yet.
        judge_reports: list[dict[str, Any]] = []
        judge_payload = brief.get("judge")
        if isinstance(judge_payload, dict):
            judge_reports.append(judge_payload)
        trace.setdefault("judge_reports", judge_reports)

        return {
            "run_id": str(run_id),
            "status": record.status,
            "prompt": record.prompt,
            "symbol": record.symbol,
            "created_at": record.created_at,
            "finished_at": record.finished_at,
            "trace": trace,
        }

    # ================================================================= #
    # Snapshot                                                          #
    # ================================================================= #

    async def get_snapshot(
        self,
        user_id: UUID,
        symbol: str,
    ) -> Optional["SnapshotRecord"]:
        """Return the fresh Snapshot for ``(user_id, symbol)`` or ``None``.

        Delegates to :class:`SnapshotStore.get_fresh_snapshot`. When
        no store was injected, the method returns ``None`` so callers
        can fall through to a full run without a hard error — the
        Snapshot is a cache, not a required component (Req 11.4,
        design §3.10).

        Requirements: 5.5, 11.4
        """
        if self._snapshot_store is None:
            return None
        return await self._snapshot_store.get_fresh_snapshot(user_id, symbol)

    # ================================================================= #
    # Ingestion / index                                                 #
    # ================================================================= #

    async def upload_document(
        self,
        user_id: UUID,
        filename: str,
        content: bytes,
        *,
        symbol: Optional[str] = None,
    ) -> dict[str, Any]:
        """Persist an uploaded PDF to the ingestion watch folder.

        Writes ``content`` to
        ``data/research/uploads/{user_id}__{symbol}__{filename}`` so
        the existing user-upload watcher (Phase 5 Task 5.4) picks it
        up. Returns ``{document_id: <uuid4-placeholder>, path}`` so
        the router can emit a stable response even before the
        indexer has finished parsing the file — the real
        ``document_id`` is assigned by the ingest pipeline once the
        file hits ``research_documents``.

        Requirements: 3.1
        """
        from pathlib import Path

        # The symbol prefix matches :mod:`src.research.ingest.sources.user_uploads`
        # which derives the symbol from the filename prefix
        # ``SYMBOL__<...>.pdf``. We also prepend the user_id so
        # uploads from different tenants cannot collide in the same
        # directory — the watcher ignores the prefix segment but the
        # filesystem needs it.
        safe_filename = Path(filename).name  # strip any path components
        sym = (symbol or "NA").upper().strip()
        target_dir = Path("data") / "research" / "uploads"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{user_id}__{sym}__{safe_filename}"
        target.write_bytes(content)

        logger.info(
            "research upload ok user=%s symbol=%s filename=%s bytes=%d",
            user_id,
            sym,
            safe_filename,
            len(content),
        )
        return {
            "document_id": str(uuid4()),  # placeholder; ingest assigns the real one
            "path": str(target),
            "symbol": sym,
            "filename": safe_filename,
            "size_bytes": len(content),
        }

    async def reindex(self, user_id: UUID, symbol: str) -> dict[str, Any]:
        """Publish a reindex request for ``(user_id, symbol)``.

        Because chunk_id derivation is content-hash-driven (Req 3.12),
        a reindex over unchanged content is a no-op at the vector
        store level — idempotency is guaranteed by construction.
        Emits an event on ``research:index_events`` so the indexer
        worker can pick the request up; returns the request id so
        the caller can correlate.

        Requirements: 3.12
        """
        request_id = uuid4()
        payload = {
            "request_id": str(request_id),
            "user_id": str(user_id),
            "symbol": symbol.upper().strip(),
            "kind": "reindex_request",
        }
        if self.redis is not None:
            try:
                # ``research:index_events`` is the canonical stream
                # for new-document + reindex events (design §4.3).
                await self.redis.xadd(
                    "research:index_events",
                    {k: str(v) for k, v in payload.items()},
                )
            except Exception:
                logger.exception("Failed to publish reindex event to Redis")
        return {
            "request_id": str(request_id),
            "status": "queued",
            "symbol": payload["symbol"],
        }

    # ================================================================= #
    # Memory                                                            #
    # ================================================================= #

    async def forget_memory(
        self,
        user_id: UUID,
        scope: str,
    ) -> dict[str, Any]:
        """Delete memory entries for ``user_id`` at ``scope``.

        Thin wrapper around :func:`src.research.memory.forget.forget_memory`.
        Requires the memory-stack triple supplied at construction;
        when absent, raises :class:`ConfigMissingError` with the
        key name the operator must wire.

        Requirements: 4.8, 4.9
        """
        if self._memory_stack is None:
            raise ConfigMissingError(
                "research.memory_stack",
                "ResearchService was constructed without a memory_stack; "
                "forget_memory is unavailable until the stack is wired.",
            )
        working, semantic, episodic = self._memory_stack

        # Imported lazily so the test matrix can construct a service
        # without pulling the memory module into the import graph.
        from src.research.memory.forget import forget_memory as _forget

        return await _forget(
            user_id,
            scope,
            working=working,
            semantic=semantic,
            episodic=episodic,
            audit_log_writer=self._audit_log_writer,
        )

    # ================================================================= #
    # Health (Task 18.4 — real per-component probes)                    #
    # ================================================================= #

    async def health(self) -> dict[str, Any]:
        """Aggregated health report (Task 18.4, design §15).

        Replaces the Phase-1 stub with real per-component probes. Each
        probe is wrapped in a short timeout (``_HEALTH_PROBE_TIMEOUT_SEC``)
        so a slow or unreachable dependency cannot hang the endpoint.
        Every probe catches its own exceptions and collapses failure
        to a structured ``{"status": "error", "error": "<reason>"}``
        payload — the health endpoint is a read-only diagnostic, so it
        must never itself raise.

        Returned shape matches design §15::

            {
              "status": "ok" | "degraded",
              "components": {
                "vector_store": {
                  "backend": "pgvector", "status": "ok", "count": 18423
                },
                "embeddings_provider": {
                  "model": "BAAI/bge-small-en-v1.5", "status": "ok"
                },
                "llm_provider": {
                  "provider": "nvidia_nim",
                  "model": "...",
                  "status": "ok"
                },
                "redis": "ok",
                "postgres": "ok",
              }
            }

        The top-level ``status`` is ``"ok"`` when every component is
        healthy, ``"degraded"`` when one or more probes failed, and
        ``"pending"`` when the service is not yet fully wired (no
        providers injected). Operators can key their alerting off the
        top-level field and drill into ``components`` for specifics.

        Requirements: 7.7
        Design: §15
        """
        components: dict[str, Any] = {
            "vector_store": await _probe_vector_store(
                self._vector_store,
                _get_resolved_backend(),
            ),
            "embeddings_provider": await _probe_embeddings(
                self._embeddings_provider,
            ),
            "llm_provider": await _probe_llm(self._llm_provider),
            "redis": await _probe_redis(self.redis),
            "postgres": await _probe_postgres(self.db_pool),
        }
        if self._orchestrator_factory is not None:
            components["orchestrator"] = "configured"
        return {
            "status": _aggregate_status(components),
            "components": components,
        }

    # ================================================================= #
    # RLS connection helper (Task 4.3)                                  #
    # ================================================================= #

    @asynccontextmanager
    async def connection(
        self,
        user_id: UUID | str,
    ) -> AsyncIterator["asyncpg.Connection"]:
        """Yield an RLS-engaged asyncpg connection for ``user_id``.

        Preserves the canonical connection-acquisition contract from
        the Phase-1 stub (Task 4.3) so downstream research code that
        imports ``ResearchService.connection`` keeps working after
        the Task 16.1 extension lands.

        Requirements: 4.6, 8.5
        Design: §14
        """
        pool = self.db_pool if self.db_pool is not None else get_pg_pool()
        if pool is None:
            raise RuntimeError(
                "ResearchService.connection requires the gateway's asyncpg "
                "pool to be initialised; call db_service.create_pg_pool() "
                "during startup and verify DATABASE_URL is set and reachable."
            )
        async with rls_connection(pool, user_id) as conn:
            yield conn

    # ================================================================= #
    # Internal helpers                                                  #
    # ================================================================= #

    def _require_owned_run(self, user_id: UUID, run_id: UUID) -> RunRecord:
        """Return the :class:`RunRecord` for ``run_id`` if owned by ``user_id``.

        Raises :class:`KeyError` on missing or foreign run — the
        router translates both to 404 so the error shape never leaks
        existence (``"not found"`` for a foreign run is informative
        but still safe; returning 403 would confirm the ID exists).
        """
        record = self._runs.get(run_id)
        if record is None:
            raise KeyError(f"Research run {run_id} not found")
        if record.user_id != user_id:
            raise KeyError(f"Research run {run_id} not found")
        return record

    async def _publish_run_request(self, record: RunRecord) -> None:
        """XADD a run request onto ``research:runs`` for out-of-process workers.

        Errors are swallowed — the in-process orchestrator task
        dispatched immediately afterwards is the authoritative path
        when there is no external worker. Design §2.2 documents the
        role of the stream: an optional fan-out queue for deployments
        that prefer to run the orchestrator outside the gateway
        process.
        """
        if self.redis is None:
            return
        try:
            await self.redis.xadd(
                RESEARCH_RUNS_STREAM,
                {
                    "run_id": str(record.run_id),
                    "user_id": str(record.user_id),
                    "symbol": record.symbol or "",
                    "prompt": record.prompt,
                },
            )
        except Exception:
            logger.exception(
                "Failed to publish run request onto %s; in-process orchestrator "
                "will still execute the run.",
                RESEARCH_RUNS_STREAM,
            )

    async def _run_in_background(self, record: RunRecord) -> None:
        """Dispatch the orchestrator, fold the result into ``record``.

        Captures every failure mode so the background task never
        raises (which would otherwise turn into a dangling
        ``_GatheringFuture`` warning on gateway shutdown). The final
        state is written onto :class:`RunRecord` and a terminal
        ``event=done`` marker is published on ``research:partials``
        so Socket.IO subscribers close their channels (design §5.2).
        """
        assert self._orchestrator_factory is not None  # checked in start_run
        publisher = self._build_partials_publisher()

        try:
            orchestrator = self._orchestrator_factory()
        except Exception as exc:
            logger.exception("Failed to build orchestrator for run %s", record.run_id)
            self._mark_error(record, exc)
            await self._publish_done(publisher, record.run_id, quality="low")
            return

        try:
            brief = await orchestrator.run(
                run_id=record.run_id,
                user_id=record.user_id,
                symbol=record.symbol,
                user_prompt=record.prompt,
            )
        except Exception as exc:
            logger.exception("Research run %s failed", record.run_id)
            self._mark_error(record, exc)
            await self._publish_done(publisher, record.run_id, quality="low")
            return

        record.brief = _coerce_brief_to_dict(brief)
        record.finished_at = time.time()
        record.status = _status_from_brief(record.brief)
        record.trace = _extract_trace(record.brief)

        # The orchestrator itself publishes a ``done`` marker from its
        # :meth:`~ResearchOrchestrator._publish_done` call, so we
        # don't duplicate it here when the orchestrator handled its
        # own publishing. But when the injected publisher is the
        # gateway's own (tests may set it up this way), the
        # orchestrator writes through the same callable and we don't
        # need to publish again. Keeping this call explicit makes the
        # contract clear: gateway-side code guarantees a terminal
        # marker on Redis whether or not the orchestrator emitted
        # one itself.
        quality = str(record.brief.get("quality", "normal")) if record.brief else "low"
        await self._publish_done(publisher, record.run_id, quality=quality)

    def _build_partials_publisher(self) -> PartialsPublisher:
        """Build the partials publisher for the current run.

        Uses :class:`RedisPartialsPublisher` when a Redis client is
        wired; otherwise a :class:`NoopPartialsPublisher` so tests
        that only care about the in-memory :class:`RunRecord`
        transitions don't need a Redis at all.
        """
        if self.redis is not None:
            return RedisPartialsPublisher(self.redis)
        return NoopPartialsPublisher()

    def _mark_error(self, record: RunRecord, exc: BaseException) -> None:
        """Flip ``record`` to ``status="error"`` with trace context."""
        record.status = "error"
        record.finished_at = time.time()
        record.trace = {
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
            }
        }

    async def _publish_done(
        self,
        publisher: PartialsPublisher,
        run_id: UUID,
        *,
        quality: str,
    ) -> None:
        """Publish the terminal ``event=done`` marker for ``run_id``."""
        try:
            await publisher(
                RESEARCH_PARTIALS_STREAM,
                format_done(run_id, quality=quality),
            )
        except Exception:
            logger.exception(
                "Failed to publish terminal done marker for run %s", run_id
            )


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _coerce_brief_to_dict(brief: Any) -> dict[str, Any]:
    """Coerce an Orchestrator return value to a plain dict.

    :meth:`ResearchOrchestrator.run` currently returns a ``dict`` but
    Task 13.8 will swap it for a :class:`~pydantic.BaseModel`
    ``ResearchBrief``. Accept both so the gateway survives the swap
    without a breaking change.
    """
    if isinstance(brief, dict):
        return brief
    # BaseModel-like: prefer ``model_dump`` (pydantic v2), then ``dict()``.
    for attr in ("model_dump", "dict"):
        fn = getattr(brief, attr, None)
        if callable(fn):
            try:
                result = fn()
                if isinstance(result, dict):
                    return result
            except Exception:
                continue
    # Fall back to attribute-scraping for surprising objects.
    try:
        return dict(brief.__dict__)  # type: ignore[no-any-return]
    except Exception:
        return {"raw": repr(brief)}


def _status_from_brief(brief: dict[str, Any]) -> RunStatus:
    """Translate a brief payload to a terminal :data:`RunStatus`.

    * ``partial=true`` or ``budget_exhausted=true`` → ``"partial"``.
    * ``quality == "low"`` → ``"partial"`` (re-synthesis loop
      exhausted, design §11.2) since the brief is still displayable
      but the gateway wants the UI badge.
    * else → ``"done"``.
    """
    if brief.get("partial") or brief.get("budget_exhausted"):
        return "partial"
    if str(brief.get("quality", "normal")).lower() == "low":
        return "partial"
    return "done"


def _extract_trace(brief: dict[str, Any]) -> dict[str, Any]:
    """Pull the trace subset out of a brief payload for ``get_run_trace``.

    Returns whatever the orchestrator stashed under ``trace`` or
    ``provenance`` — both keys are possible while the full
    ``ResearchBrief`` Pydantic model is still in flight (Task 13.8).
    """
    trace: dict[str, Any] = {}
    for key in ("trace", "provenance", "plan_md", "partial", "quality"):
        if key in brief:
            trace[key] = brief[key]
    return trace


# --------------------------------------------------------------------------- #
# Task 18.4 — health probes                                                   #
# --------------------------------------------------------------------------- #
#
# Per design §15, ``GET /api/v2/research/health`` reports per-component
# status for ``vector_store``, ``embeddings_provider``, ``llm_provider``,
# ``redis``, and ``postgres``. Each probe lives as a free function
# below so :meth:`ResearchService.health` stays short and every probe
# is independently testable.
#
# Every probe:
#
# * Runs under a short timeout so a slow/unreachable dependency does
#   not hang the endpoint (Task 18.4 "short timeout ~500ms").
# * Catches every exception internally and collapses failures to a
#   structured dict with ``status="error"`` + a short ``error``
#   string. The health endpoint must never itself raise.
# * Returns ``"pending"`` when the collaborator is missing — i.e.
#   the service hasn't been fully wired. Matches the Phase-1
#   behaviour so operators keep seeing the same field.


_HEALTH_PROBE_TIMEOUT_SEC: float = 0.5


def _get_resolved_backend() -> str | None:
    """Return the vector-store backend auto-resolved at boot (or ``None``).

    Indirection wraps :func:`get_resolved_vector_store_backend` so test
    doubles can stub the resolution without monkey-patching the
    registry import.
    """
    return get_resolved_vector_store_backend()


async def _probe_vector_store(
    store: Any,
    resolved_backend: str | None,
) -> dict[str, Any]:
    """Probe the active :class:`VectorStore` (Task 18.4, design §15).

    Reports the backend name (auto-resolved via the registry cache
    populated at boot, design §8), the health status, and the total
    chunk count visible to the store — the latter is a cheap
    "storage reachable" signal that doubles as a sanity check for
    operators migrating between backends.

    ``count`` defaults to ``None`` when the probe fails, when the
    store hasn't been injected, or when the backend's
    :meth:`~VectorStore.count` cannot execute under the probe timeout.
    """
    # Not-yet-wired case: preserve the Phase-1 contract where the
    # backend field surfaces the auto-resolved name once the §8
    # decision tree has run at least once. Without an injected store
    # we cannot probe counts, but operators still see the backend.
    if store is None:
        if resolved_backend:
            return {"backend": resolved_backend, "status": "pending"}
        return {"status": "pending"}

    try:
        # :meth:`count` takes a :class:`RetrievalFilter`. We pass a
        # "system" probe filter — the filter shape requires a
        # ``user_id``, so we use a zero UUID which intentionally
        # matches no rows; the probe measures "store responded"
        # rather than "specific count". Backends that short-circuit
        # on unknown user ids still validate connectivity.
        from src.research.providers.base import RetrievalFilter  # noqa: PLC0415

        probe_filter = RetrievalFilter(user_id=UUID(int=0))
        count = await asyncio.wait_for(
            store.count(probe_filter),
            timeout=_HEALTH_PROBE_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        return {
            "backend": resolved_backend or _describe_backend(store),
            "status": "error",
            "error": "timeout",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "backend": resolved_backend or _describe_backend(store),
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }

    return {
        "backend": resolved_backend or _describe_backend(store),
        "status": "ok",
        "count": int(count) if isinstance(count, (int, float)) else None,
    }


def _describe_backend(store: Any) -> str:
    """Best-effort backend name when the registry cache hasn't been populated.

    Falls back to the class's module name — good enough for the
    diagnostic surface when the auto-selection path was not used
    (e.g. an operator override wired the store directly).
    """
    module = getattr(type(store), "__module__", "") or ""
    # ``src.research.providers.vector_store.pgvector`` → ``pgvector``.
    return module.rsplit(".", 1)[-1] or "unknown"


async def _probe_embeddings(provider: Any) -> dict[str, Any]:
    """Probe the active :class:`EmbeddingsProvider` (Task 18.4, design §15).

    The probe does a single-token embed under the short timeout so
    both the model loader (for local sentence-transformers) and the
    network path (for NVIDIA NIM / OpenAI / Ollama) are exercised.
    The returned ``model`` field doubles as an identity badge so
    operators can confirm a redeployment picked up the new config
    without grepping logs.
    """
    if provider is None:
        return {"status": "pending"}

    try:
        model_id = getattr(provider, "model_id", None)
        model = str(model_id) if model_id else "unknown"
    except Exception:  # noqa: BLE001 - defensive
        model = "unknown"

    try:
        result = await asyncio.wait_for(
            provider.embed(["health"]),
            timeout=_HEALTH_PROBE_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        return {"model": model, "status": "error", "error": "timeout"}
    except Exception as exc:  # noqa: BLE001
        return {"model": model, "status": "error", "error": f"{type(exc).__name__}: {exc}"}

    # A healthy embedder returns ``list[list[float]]`` with one entry
    # per input text. Anything else is a provider bug but we report
    # ``error`` rather than raising so the rest of the health report
    # is still visible.
    if not isinstance(result, list) or not result or not isinstance(result[0], list):
        return {"model": model, "status": "error", "error": "invalid embedding shape"}
    return {"model": model, "status": "ok"}


async def _probe_llm(provider: Any) -> dict[str, Any]:
    """Probe the active :class:`LLMProvider` (Task 18.4, design §15).

    Unlike the embeddings probe we deliberately do **not** issue a
    chat-completion here — a network round-trip to the LLM endpoint
    would (a) cost tokens on every ``GET /health`` call and (b) likely
    exceed the 500 ms timeout under normal conditions. Instead we
    check the provider exposes the expected identity fields
    (``provider``, ``model``) and short-circuit to ``"ok"`` when both
    are present. A richer "live" probe is a Phase-20 observability
    enhancement (Task 20.x).

    The "reachable-but-not-queried" signal matches how other gateway
    health checks treat the LLM — see ``backend-gateway/app/routers/health.py``
    for the same pattern.
    """
    if provider is None:
        return {"status": "pending"}

    try:
        name = _provider_name(provider)
        model = _provider_model(provider)
    except Exception as exc:  # noqa: BLE001 - defensive
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}

    payload: dict[str, Any] = {"status": "ok"}
    if name:
        payload["provider"] = name
    if model:
        payload["model"] = model
    return payload


def _provider_name(provider: Any) -> str | None:
    """Best-effort provider-name extraction.

    Adapters under ``src/research/providers/llm/`` expose a
    ``provider`` attribute (see design §3.1 ``Completion.provider``);
    fall back to the module tail otherwise.
    """
    for attr in ("provider", "_provider", "name"):
        value = getattr(provider, attr, None)
        if isinstance(value, str) and value:
            return value
    module = getattr(type(provider), "__module__", "") or ""
    tail = module.rsplit(".", 1)[-1]
    return tail or None


def _provider_model(provider: Any) -> str | None:
    """Best-effort model-id extraction from an LLM provider."""
    for attr in ("model", "_model", "model_id"):
        value = getattr(provider, attr, None)
        if isinstance(value, str) and value:
            return value
    return None


async def _probe_redis(redis_client: Any) -> str | dict[str, str]:
    """Probe the Redis connection (Task 18.4, design §15).

    Returns the literal string ``"ok"`` on success to match the
    design §15 JSON shape (``"redis": "ok"``); on failure returns
    a structured dict with a ``status`` + ``error`` pair so operators
    can see the failure mode without reading gateway logs.
    """
    if redis_client is None:
        return "pending"
    try:
        await asyncio.wait_for(
            redis_client.ping(),
            timeout=_HEALTH_PROBE_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        return {"status": "error", "error": "timeout"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
    return "ok"


async def _probe_postgres(pool: Any) -> str | dict[str, str]:
    """Probe the Postgres connection pool (Task 18.4, design §15).

    Uses ``fetchval("SELECT 1")`` as the canonical "server reachable
    and accepting queries" probe. When the pool is not present falls
    back to :func:`get_pg_pool` so a service constructed without an
    explicit pool still probes the gateway's global pool.
    """
    effective_pool = pool if pool is not None else get_pg_pool()
    if effective_pool is None:
        return "pending"
    try:
        async def _query() -> None:
            async with effective_pool.acquire() as conn:
                await conn.fetchval("SELECT 1")

        await asyncio.wait_for(_query(), timeout=_HEALTH_PROBE_TIMEOUT_SEC)
    except asyncio.TimeoutError:
        return {"status": "error", "error": "timeout"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
    return "ok"


def _aggregate_status(components: Mapping[str, Any]) -> str:
    """Derive the top-level status from individual component results.

    * ``"ok"``       — every component is ``"ok"``.
    * ``"degraded"`` — at least one component returned ``"error"``.
    * ``"pending"``  — at least one component is ``"pending"`` but
                      none have errored.
    """
    has_error = False
    has_pending = False
    for value in components.values():
        if isinstance(value, str):
            if value == "error":
                has_error = True
            elif value == "pending":
                has_pending = True
        elif isinstance(value, Mapping):
            status = value.get("status")
            if status == "error":
                has_error = True
            elif status == "pending":
                has_pending = True
    if has_error:
        return "degraded"
    if has_pending:
        return "pending"
    return "ok"
