"""Research Orchestrator — plan → fan-out → synthesise → validate → Judge → emit (design §3.5).

This module hosts the top-level agent that drives a single
``Research_Run``. It realises the LangGraph shape documented in design
§3.5 as a plain-asyncio state machine. LangGraph is not yet a
dependency of the project (see ``pyproject.toml``), so the graph is
expressed as a straight-line coroutine in :meth:`ResearchOrchestrator.run`
with a semaphore-capped :func:`asyncio.gather` for the concurrent
fan-out. The shape — plan → fan-out (cap 6) → synthesise → numeric
validate → Judge → re-synthesis (≤1x) → emit — matches the graph on a
one-to-one basis, so the module can be ported to LangGraph without any
API break when the dependency lands.

Structural, not final
---------------------
This is Task 13.1 of Phase 12. Sub_Agents (Tasks 13.2–13.7),
Report_Synthesizer (Task 13.8), token-budget tracker (Task 13.9), and
the ``ResearchBrief`` Pydantic model (Task 13.8) all arrive later in
Phase 12. The Orchestrator is therefore written to **inject** those
collaborators at construction time — every dependency is a Protocol
or a callable, not a concrete import. That keeps this file usable
today without touching un-implemented modules and preserves a clean
seam for the subsequent tasks.

Public surface
--------------
* :class:`AgentResult` — one Sub_Agent's contribution to a run.
  Pre-figures the Pydantic ``AgentResult`` that Task 13.8 will ship
  (design §4.2); kept as a ``dataclass`` for now because nothing in
  this file needs validation beyond the dataclass's own constructor.
* :class:`PlanOutput` — the plan node's decision about which
  Sub_Agents to invoke and per-agent retrieval intents.
* :class:`ResearchOrchestrator` — the class. Construct once per
  worker with the Sub_Agent list and the validator / judge / publisher
  contracts; call :meth:`run` per request.

Satisfies
---------
* Req 1.1 — ``research.run(symbol, prompt, user_id)`` operation that
  produces exactly one brief per run.
* Req 1.5 — returned brief carries the canonical section set from
  design §3.5 (sections are assembled in :meth:`run`; the enumeration
  is authoritative via :data:`_BRIEF_SECTIONS`).
* Req 1.7 — partial results stream to the caller as each Sub_Agent
  completes, via the injected publisher writing to
  :data:`RESEARCH_PARTIALS_STREAM` (design §4.3).
* Req 5.4 — concurrency cap (default 6) via :class:`asyncio.Semaphore`.

Design references
-----------------
* §2.1 — top-down diagram (plan + fan-out + synth + validators + Judge).
* §3.5 — Orchestrator graph shape and per-agent configurability.
* §3.7 — ``JudgeReport`` schema consumed by the re-synthesis loop.
* §3.8 — numeric validator consumed before the Judge.
* §3.11 — ``research:partials`` stream used by the publisher.
* §11.2 — single re-synthesis loop (delegated to
  :mod:`src.research.judge.resynthesis`).
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import (
    Any,
    Final,
    Protocol,
    runtime_checkable,
)
from uuid import UUID

from src.research.agents.logging import (
    log_orchestrator_event,
    log_sub_agent_invocation,
)
from src.research.agents.partials import (
    PartialsPublisher,
    format_agent_partial,
    format_done,
)
from src.research.constants import RESEARCH_PARTIALS_STREAM
from src.research.judge.judge import JudgeReport
from src.research.judge.resynthesis import (
    ResynthesisOutcome,
    run_resynthesis_loop,
)
from src.research.providers.base import (
    ChunkHit,
    LLMParams,
    LLMProvider,
    Message,
)
from src.research.validators.citation_validator import CitationValidator
from src.research.validators.numeric_validator import NumericValidator
from src.research.validators.types import UnsupportedClaim

# ``src.utils.logger`` provides the project-standard structured logger.
# Fall back to stdlib ``logging`` when it cannot be imported — matches
# the pattern used by :mod:`src.research.cache.latency_events` and
# :mod:`src.research.judge.async_fallback` so observability wiring stays
# uniform under trimmed test installs.
try:  # pragma: no cover - import-path fallback
    from src.utils.logger import get_logger

    _logger: Any = get_logger("ResearchOrchestrator")
except Exception:  # noqa: BLE001 - best-effort logger wiring
    import logging

    _logger = logging.getLogger("research.agents.orchestrator")


__all__ = [
    "AgentResult",
    "JudgeFn",
    "PartialsPublisher",
    "PlanOutput",
    "ResearchOrchestrator",
    "SubAgent",
    "Synthesizer",
]


# --------------------------------------------------------------------------- #
# Constants                                                                   #
# --------------------------------------------------------------------------- #


# Canonical brief section list (design §3.5, Req 1.5). Kept duplicated
# against ``src.research.validators.numeric_validator._BRIEF_SECTION_NAMES``
# and ``src.research.judge.judge._BRIEF_SECTION_NAMES`` for the same
# reason those modules keep their own copy: the authoritative
# ``ResearchBrief`` Pydantic model lands in Task 13.8, after which every
# site imports from there.
_BRIEF_SECTIONS: Final[tuple[str, ...]] = (
    "summary",
    "thesis",
    "risks",
    "financial_highlights",
    "management_commentary",
    "technical_view",
    "peers",
    "macro_context",
)

# Default concurrency cap for the fan-out (design §7.1
# ``research.concurrency.per_run_max_subagents``, Req 5.4). The
# Orchestrator honours an operator override through the constructor.
_DEFAULT_CONCURRENCY_CAP: Final[int] = 6

# Default re-synthesis retry budget. Req 16.18 caps the loop at one
# pass; exposed so the Orchestrator can force ``max_retries=0`` when
# a run is already flagged ``budget_exhausted`` (Task 13.9).
_DEFAULT_MAX_RETRIES: Final[int] = 1

# Default Judge pass-threshold (``research.judge.min_score``, design
# §7.1). Mirrored here so the Orchestrator can drive the re-synthesis
# loop without re-reading config on every run.
_DEFAULT_MIN_SCORE: Final[float] = 0.7

# Plan-node LLM defaults. The plan prompt is short and deterministic;
# callers can override via the ``plan_llm_params`` hook if a more
# exploratory temperature is wanted (design §3.5 "plan node calls
# research.providers.chat.*").
_DEFAULT_PLAN_TEMPERATURE: Final[float] = 0.0
_DEFAULT_PLAN_MAX_TOKENS: Final[int] = 512


# --------------------------------------------------------------------------- #
# Lightweight dataclasses                                                     #
# --------------------------------------------------------------------------- #


@dataclass
class AgentResult:
    """One Sub_Agent's contribution to a ``Research_Run`` (design §4.2 preview).

    This pre-figures the Pydantic ``AgentResult`` that Task 13.8 will
    introduce. It is a plain :class:`dataclass` for now because nothing
    here needs Pydantic validation beyond "the fields exist" — the
    Orchestrator always fills every field itself.

    Attributes
    ----------
    agent_name:
        The Sub_Agent's registry name (``"filings"``,
        ``"fundamentals"``, ``"news_sentiment"``, …). Conventionally
        matches the ``Sub_Agent`` enum that Task 13.8 will define.
    kind:
        One of ``"ok" | "no_data" | "error"`` (Req 1.3, Req 1.6).
        ``"no_data"`` keeps the run alive without a section; ``"error"``
        marks the run ``partial=true``.
    section_name:
        The brief section this Sub_Agent populates (e.g. ``"thesis"``
        for the Fundamentals Agent). Used by the Report_Synthesizer in
        Task 13.8 to thread content into the right brief field.
    section_md:
        Markdown body the Sub_Agent contributed. Empty string when
        ``kind != "ok"``.
    chunks:
        Cited chunks this Sub_Agent retrieved. Aggregated in :meth:`run`
        and fed into the numeric + citation validators and the Judge
        so each layer works off the same provenance set.
    wall_time_ms, input_tokens, output_tokens:
        Provenance metrics (Req 1.8). Captured by the Sub_Agent and
        echoed verbatim so Task 13.9's usage writer can stamp
        ``llm_usage`` rows without re-measuring.
    reason:
        Free-text reason when ``kind != "ok"`` (e.g. ``"no_data: no
        BSE filings for RELIANCE"``). Surfaced in the trace
        (Req 13.3) and in the UI's ``NoDataState`` component.

    """

    agent_name: str
    kind: str = "ok"
    section_name: str = ""
    section_md: str = ""
    chunks: list[ChunkHit] = field(default_factory=list)
    wall_time_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reason: str = ""

    def to_payload(self) -> dict[str, Any]:
        """Serialise to a plain dict for the partials stream payload.

        Keeps the payload JSON-friendly without importing the
        ``ResearchBrief`` Pydantic model (not yet landed). ``chunks``
        is compressed to the list of chunk_ids so the partial event is
        cheap over the wire — the full chunk set stays on the
        Orchestrator side and is only serialised once into the final
        brief's citations.
        """
        return {
            "agent_name": self.agent_name,
            "kind": self.kind,
            "section_name": self.section_name,
            "section_md": self.section_md,
            "chunk_ids": [hit.chunk.chunk_id for hit in self.chunks],
            "wall_time_ms": self.wall_time_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "reason": self.reason,
        }


@dataclass
class PlanOutput:
    """Plan node output — which Sub_Agents to run and why (design §3.5).

    The plan node is deliberately minimal in this first iteration
    (Task 13.1 is structural). By default it selects every injected
    Sub_Agent; operators / future tasks can tighten the selection by
    replacing the plan function or overriding :meth:`_run_plan`.
    """

    agents_requested: list[str]
    retrieval_plan: dict[str, str] = field(default_factory=dict)
    plan_md: str = ""


# --------------------------------------------------------------------------- #
# Protocols — injected collaborators                                          #
# --------------------------------------------------------------------------- #


@runtime_checkable
class SubAgent(Protocol):
    """Abstract Sub_Agent invoked by the Orchestrator (design §3.5).

    The contract is a single async method :meth:`invoke` returning an
    :class:`AgentResult`. Sub_Agent instances are injected at
    Orchestrator construction time — the Sub_Agent implementations
    themselves land in Tasks 13.2–13.7.

    Sub_Agents MUST NOT raise on a ``no_data`` condition; they return
    ``AgentResult(kind="no_data", reason=…)`` instead (Req 1.3).
    Exceptions are caught by :meth:`ResearchOrchestrator._invoke_agent`
    and converted to ``AgentResult(kind="error", …)`` so one bad
    Sub_Agent cannot take down the whole run (Req 1.6).
    """

    name: str

    async def invoke(self, context: AgentContext) -> AgentResult:
        """Run the Sub_Agent and return its result."""
        ...


@dataclass
class AgentContext:
    """Per-run context handed to every Sub_Agent (design §3.5).

    Bundles the inputs that every Sub_Agent needs — the run id, the
    user, the symbol (may be ``None`` for generic queries, Req 1.5),
    the prompt, and the concrete retriever. The Orchestrator builds
    one instance per run and reuses it across the fan-out.

    The retriever is exposed as the opaque ``retriever`` attribute
    rather than a concrete type so the Phase 6 ``HybridRetriever`` and
    any Phase 8 cached variants satisfy the contract uniformly.
    """

    run_id: UUID
    user_id: UUID
    symbol: str | None
    user_prompt: str
    retriever: Any
    plan: PlanOutput


# Synthesizer contract. The Report_Synthesizer (Task 13.8) consumes
# the Sub_Agent outputs and emits a brief. Represented here as a
# duck-typed async callable so this module stays usable before
# Task 13.8 ships. The re-synthesis path uses a subset of the same
# contract (extra ``prior_brief`` + feedback kwargs) — see
# :meth:`ResearchOrchestrator._build_synthesize_fn_for_resynthesis`.
#
# First-pass signature:
#     async def synthesize(
#         *,
#         agent_results: Sequence[AgentResult],
#         symbol: str | None,
#         user_prompt: str,
#     ) -> Mapping[str, str]
#
# Re-synthesis signature (design §11.2):
#     async def synthesize(
#         *,
#         prior_brief: Mapping[str, str] | object,
#         unsupported_claims: tuple[UnsupportedClaim, ...],
#         numeric_findings: tuple[UnsupportedClaim, ...],
#     ) -> Mapping[str, str]
Synthesizer = Callable[..., Awaitable[Any]]

# Judge callable. In production this is a ``functools.partial`` over
# :func:`src.research.judge.invoke` that captures the run id, the
# chunks, the numeric findings, and the Judge's LLM provider. The
# re-synthesis loop supplies ``brief`` and ``retry_count``.
JudgeFn = Callable[..., Awaitable[JudgeReport]]

# Publisher for the ``research:partials`` stream. Takes
# ``(stream_name, fields_dict)`` and returns an awaitable so the
# Orchestrator can inject a fake publisher in tests without a real
# Redis. Consolidated in :mod:`src.research.agents.partials` — imported
# above and re-exported via ``__all__`` for backwards compatibility
# with callers that still import it from this module.


# --------------------------------------------------------------------------- #
# Default plan function                                                       #
# --------------------------------------------------------------------------- #


async def _default_plan(
    *,
    chat_llm: LLMProvider | None,
    user_prompt: str,
    available_agents: Sequence[str],
) -> PlanOutput:
    """Minimal plan function: invoke every available Sub_Agent.

    The plan node is structural in Task 13.1 — we call the chat LLM
    once to produce a short plan summary (so the provider integration
    is live and testable), but the selection itself fans out to all
    injected Sub_Agents. Future tasks tighten the selection by
    replacing this function via the ``plan_fn`` constructor hook.

    When ``chat_llm`` is ``None`` (the construction path used by unit
    tests that don't want to model an LLM call), the plan is returned
    synchronously with an empty ``plan_md``.
    """
    if chat_llm is None:
        return PlanOutput(
            agents_requested=list(available_agents),
            retrieval_plan=dict.fromkeys(available_agents, user_prompt),
            plan_md="",
        )

    # A very short prompt. We do not want to spend tokens on a full
    # planner in Task 13.1 — the structural plan node exists to prove
    # out the ``research.providers.chat.*`` wiring.
    messages = [
        Message(
            role="system",
            content=(
                "You are the Research Orchestrator planner. Given the user prompt "
                "and the list of available specialist agents, produce a one-line "
                "plan describing which agents you will consult and why. Do not "
                "invent agents; pick only from the provided list."
            ),
        ),
        Message(
            role="user",
            content=(
                f"Available agents: {', '.join(available_agents)}\n"
                f"User prompt: {user_prompt}"
            ),
        ),
    ]
    params = LLMParams(
        temperature=_DEFAULT_PLAN_TEMPERATURE,
        max_tokens=_DEFAULT_PLAN_MAX_TOKENS,
    )
    try:
        completion = await chat_llm.complete(messages, params)
        plan_md = completion.content
    except Exception as exc:  # noqa: BLE001 — best-effort plan
        _log_warning(
            "research plan LLM call failed; proceeding with full fan-out",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        plan_md = ""

    return PlanOutput(
        agents_requested=list(available_agents),
        retrieval_plan=dict.fromkeys(available_agents, user_prompt),
        plan_md=plan_md,
    )


# --------------------------------------------------------------------------- #
# Orchestrator                                                                #
# --------------------------------------------------------------------------- #


class ResearchOrchestrator:
    """Plan → fan-out → synthesise → validate → Judge → emit (design §3.5).

    Every collaborator is injected at construction time. The class
    holds no persistent state between runs beyond the references it
    was built with, so a single instance can be shared across
    concurrent ``Research_Run``\\s as long as each Sub_Agent / judge /
    publisher is safe for concurrent use (every in-tree implementation
    is).

    Parameters
    ----------
    sub_agents:
        The list of Sub_Agents to fan out to. Order is preserved in
        the partials stream; a Sub_Agent appearing twice in the list
        is treated as two independent invocations, which simplifies
        property tests that want to exercise concurrent ordering.
    synthesizer:
        Async callable that consumes the Sub_Agent outputs and produces
        a brief. See the ``Synthesizer`` type alias for the contract.
        Callers that don't yet have a Report_Synthesizer (Task 13.8
        hasn't landed) can pass a stub that returns a plain ``dict``
        keyed by :data:`_BRIEF_SECTIONS`.
    judge_fn:
        Async callable that scores a brief. In production this is a
        ``functools.partial`` over :func:`src.research.judge.invoke`;
        tests pass a stub returning a canned :class:`JudgeReport`.
    retriever:
        The run-wide :class:`HybridRetriever` (Phase 6). Passed through
        to every Sub_Agent via :class:`AgentContext`.
    numeric_validator:
        Optional :class:`NumericValidator`. When ``None`` (the common
        case), a default instance with ``epsilon=0.01`` is created.
    citation_validator:
        Optional :class:`CitationValidator`. When ``None``, the
        citation check is skipped — the Orchestrator still runs the
        numeric validator and the Judge. Skipping is safe here because
        the Judge itself includes a citation-coverage check via the
        prompt (design §11.1); the deterministic citation validator
        is an additional belt-and-braces pass (design §3.8) that
        requires the active :class:`VectorStore`, which the caller
        may not want to wire in unit tests.
    partials_publisher:
        Async callable that writes partials onto
        :data:`RESEARCH_PARTIALS_STREAM`. Takes
        ``(stream_name, fields_dict)``. Defaults to a no-op when
        ``None`` is passed — convenient for unit tests and for the
        offline rule-based judge path that does not need to stream.
    chat_llm:
        Optional :class:`LLMProvider` for the plan node. When ``None``,
        the default plan function skips the LLM call and returns a
        plain fan-out plan (see :func:`_default_plan`). Task 13.9 and
        beyond will wire the real ``research.providers.chat.*`` role
        here.
    plan_fn:
        Optional override for the plan function. Signature::

            async def plan_fn(
                *,
                chat_llm: LLMProvider | None,
                user_prompt: str,
                available_agents: Sequence[str],
            ) -> PlanOutput

        Defaults to :func:`_default_plan`.
    concurrency_cap:
        Upper bound on concurrent Sub_Agent invocations. Default 6
        (design §7.1 ``research.concurrency.per_run_max_subagents``,
        Req 5.4).
    min_score:
        Judge pass-threshold forwarded to the re-synthesis loop.
        Defaults to the design §7.1 value of 0.7.
    max_retries:
        Re-synthesis retry budget (Req 16.18). Defaults to 1.
    full_brief_ms_budget:
        Reference-configuration full-brief latency budget in
        milliseconds — ``research.latency_budgets.full_brief_ms``
        (design §7.1, Req 5.3). Stored on the instance so callers
        (the worker layer, the async-Judge fallback decision) can
        read the effective value via
        :meth:`effective_full_brief_budget_ms`. ``None`` means "no
        budget wired" — the helper then returns ``None`` and the
        caller applies whatever fallback it likes.
    offline_full_brief_ms_budget:
        Offline full-brief budget,
        ``research.latency_budgets.offline_full_brief_ms`` (design
        §13.1, Req 15.5). When ``LOHI_RESEARCH_OFFLINE=true`` and
        this value is not ``None``, :meth:`effective_full_brief_budget_ms`
        returns it instead of ``full_brief_ms_budget`` to
        accommodate Ollama + local embeddings latency.

    """

    def __init__(
        self,
        *,
        sub_agents: Sequence[SubAgent],
        synthesizer: Synthesizer,
        judge_fn: JudgeFn,
        retriever: Any,
        numeric_validator: NumericValidator | None = None,
        citation_validator: CitationValidator | None = None,
        partials_publisher: PartialsPublisher | None = None,
        chat_llm: LLMProvider | None = None,
        plan_fn: Callable[..., Awaitable[PlanOutput]] | None = None,
        concurrency_cap: int = _DEFAULT_CONCURRENCY_CAP,
        min_score: float = _DEFAULT_MIN_SCORE,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        full_brief_ms_budget: int | None = None,
        offline_full_brief_ms_budget: int | None = None,
    ) -> None:
        if concurrency_cap < 1:
            raise ValueError(
                f"concurrency_cap must be ≥ 1; got {concurrency_cap}",
            )
        if max_retries < 0:
            raise ValueError(
                f"max_retries must be non-negative; got {max_retries}",
            )

        self._sub_agents: tuple[SubAgent, ...] = tuple(sub_agents)
        self._synthesizer = synthesizer
        self._judge_fn = judge_fn
        self._retriever = retriever
        self._numeric_validator = numeric_validator or NumericValidator()
        self._citation_validator = citation_validator
        self._partials_publisher = partials_publisher
        self._chat_llm = chat_llm
        self._plan_fn = plan_fn or _default_plan
        self._concurrency_cap = concurrency_cap
        self._min_score = min_score
        self._max_retries = max_retries
        self._full_brief_ms_budget = full_brief_ms_budget
        self._offline_full_brief_ms_budget = offline_full_brief_ms_budget

    # ------------------------------------------------------------------ #
    # Latency-budget accessors (Req 15.5, design §13.1)                  #
    # ------------------------------------------------------------------ #
    #
    # The core ``run()`` flow does **not** enforce the budget — those
    # decisions happen at the Orchestrator edge (partials-stream
    # timeouts in the worker layer, async-Judge fallback in Phase 11).
    # The helpers below give those edges a single source of truth so
    # the offline mode's relaxed budget (60 s per design §13.1) is
    # applied uniformly without duplicating the env-var check.

    def _effective_full_brief_budget_ms(self) -> int | None:
        """Return the budget appropriate to the current mode.

        Reads ``LOHI_RESEARCH_OFFLINE`` from the environment; when
        truthy **and** ``offline_full_brief_ms_budget`` was supplied,
        returns that value; otherwise returns
        ``full_brief_ms_budget`` (which may itself be ``None`` when
        the caller did not wire a budget).
        """
        offline = os.environ.get(
            "LOHI_RESEARCH_OFFLINE", "",
        ).strip().lower() in ("true", "1", "yes")
        if offline and self._offline_full_brief_ms_budget is not None:
            return self._offline_full_brief_ms_budget
        return self._full_brief_ms_budget

    @property
    def effective_full_brief_budget_ms(self) -> int | None:
        """Public read of the mode-aware full-brief budget (Req 15.5).

        Callers (the worker layer, the async-Judge fallback decision
        at design §11.3) use this to pick the right
        ``research.latency_budgets.*`` value without re-reading the
        environment. Exposed as a property so access is cheap and
        side-effect-free — the env-var probe runs on every read but
        is a single dict lookup, which is fine for the edge call
        sites that consult it once per run.
        """
        return self._effective_full_brief_budget_ms()

    # ------------------------------------------------------------------ #
    # Public entry point                                                 #
    # ------------------------------------------------------------------ #

    async def run(
        self,
        *,
        run_id: UUID,
        user_id: UUID,
        symbol: str | None,
        user_prompt: str,
    ) -> dict[str, Any]:
        """Drive one ``Research_Run`` from plan to final brief.

        The method never raises under normal operation — Sub_Agent
        exceptions are caught, logged, and converted to
        ``AgentResult(kind="error")`` (Req 1.6); synthesiser and
        judge failures reduce to a ``quality="low"`` brief via the
        re-synthesis loop (design §11.2). Callers needing a richer
        error contract (e.g. the gateway's structured error envelope,
        Req 8.8) wrap this method and translate failures from the
        returned brief's ``partial`` / ``quality`` fields.

        Parameters
        ----------
        run_id:
            Unique identifier for this run. Forwarded verbatim to the
            Judge and stamped onto every partials-stream event so the
            gateway can fan out to the right Socket.IO channel
            (design §5.2).
        user_id:
            The caller's user id. Every retrieval / memory read scopes
            on it (Req 3.10, Req 4.5).
        symbol:
            Optional ticker scope. ``None`` means "no symbol" — the
            Orchestrator still dispatches to every injected Sub_Agent;
            Sub_Agents that require a symbol typically return
            ``AgentResult(kind="no_data", reason="no symbol supplied")``.
        user_prompt:
            The raw user prompt. The Guardrail_Layer (Task 10.4) is
            expected to have pre-filtered it upstream (design §3.6);
            this method treats the prompt as opaque text.

        Returns
        -------
        dict[str, Any]
            A ``ResearchBrief``-shaped payload. The canonical Pydantic
            model lands in Task 13.8; until then this dict carries
            the same field names so Task 13.8 can swap the return
            type without touching callers.

        """
        wall_start = time.perf_counter()

        # 1) Plan — decides which Sub_Agents to invoke (design §3.5).
        plan = await self._run_plan(user_prompt)
        _safe_log_orchestrator_event(
            run_id=run_id,
            user_id=user_id,
            event="plan_done",
            agents_requested=list(plan.agents_requested),
        )

        # 2) Build the per-run context shared by every Sub_Agent.
        context = AgentContext(
            run_id=run_id,
            user_id=user_id,
            symbol=symbol,
            user_prompt=user_prompt,
            retriever=self._retriever,
            plan=plan,
        )

        # 3) Fan out — concurrent Sub_Agent invocations, cap via
        #    ``asyncio.Semaphore`` (Req 5.4). Each invocation
        #    publishes its result on ``research:partials`` the
        #    moment it completes (Req 1.7).
        selected = self._select_agents(plan.agents_requested)
        _safe_log_orchestrator_event(
            run_id=run_id,
            user_id=user_id,
            event="fan_out_start",
            agent_count=len(selected),
        )
        agent_results = await self._fan_out(context, selected)
        _safe_log_orchestrator_event(
            run_id=run_id,
            user_id=user_id,
            event="fan_out_done",
            agent_count=len(agent_results),
            error_count=sum(1 for r in agent_results if r.kind == "error"),
            no_data_count=sum(1 for r in agent_results if r.kind == "no_data"),
        )

        # 4) Synthesise — Report_Synthesizer consumes Sub_Agent outputs
        #    only (Req 1.4). First-pass synthesis is a plain call; the
        #    re-synthesis loop below uses a bound callable that
        #    forwards feedback per design §11.2.
        first_brief = await self._synthesize_first_pass(
            agent_results=agent_results,
            symbol=symbol,
            user_prompt=user_prompt,
        )
        _safe_log_orchestrator_event(
            run_id=run_id,
            user_id=user_id,
            event="synthesis_done",
        )

        # 5) Deterministic numeric validator (design §3.8, §12,
        #    Req 16.26). The Judge receives these findings verbatim.
        all_chunks = _collect_chunks(agent_results)
        numeric_findings = self._numeric_validator.validate(
            brief=first_brief,
            cited_chunks=[hit.chunk for hit in all_chunks],
        )

        # 6) Optional citation validator (design §3.8, Req 14.1).
        if self._citation_validator is not None and symbol is not None:
            citation_findings = await self._citation_validator.validate(
                brief=first_brief,
                user_id=user_id,
                symbol=symbol,
            )
        else:
            citation_findings = []

        # Combine deterministic findings — the re-synthesis loop feeds
        # the union back into the synthesiser so it sees every
        # authoritative violation.
        deterministic_findings: list[UnsupportedClaim] = list(numeric_findings)
        deterministic_findings.extend(citation_findings)

        # 7) Judge + single re-synthesis loop (design §11.2, Req 16.18).
        outcome = await self._run_judge_and_resynth(
            first_brief=first_brief,
            numeric_findings=deterministic_findings,
            agent_results=agent_results,
            symbol=symbol,
            user_prompt=user_prompt,
        )
        _safe_log_orchestrator_event(
            run_id=run_id,
            user_id=user_id,
            event="judge_done",
            quality=outcome.quality,
            retry_count=int(getattr(outcome.judge_report, "retry_count", 0)),
            safe_to_display=bool(
                getattr(outcome.judge_report, "safe_to_display", False),
            ),
        )

        # 8) Assemble the final brief payload.
        brief_payload = self._assemble_final_brief(
            outcome=outcome,
            agent_results=agent_results,
            run_id=run_id,
            symbol=symbol,
            wall_start=wall_start,
        )

        # 9) Emit a final partial so the gateway can close the channel
        #    cleanly. The final brief itself goes out through the
        #    gateway's REST response + ``research:done`` Socket.IO
        #    event (design §5.2); publishing here is a small
        #    end-of-stream marker so subscribers that only watch the
        #    partials stream know the run is done.
        await self._publish_done(run_id=run_id, quality=outcome.quality)

        return brief_payload

    # ------------------------------------------------------------------ #
    # Plan                                                               #
    # ------------------------------------------------------------------ #

    async def _run_plan(self, user_prompt: str) -> PlanOutput:
        """Invoke the plan function with the injected LLM + agent list."""
        available = [agent.name for agent in self._sub_agents]
        return await self._plan_fn(
            chat_llm=self._chat_llm,
            user_prompt=user_prompt,
            available_agents=available,
        )

    def _select_agents(self, requested: Sequence[str]) -> list[SubAgent]:
        """Resolve plan-requested agent names back to Sub_Agent instances.

        Order is the order of the plan's ``agents_requested`` list so
        per-agent latency in the fan-out partials stream mirrors the
        planner's intent. Unknown names are dropped with a log line —
        a planner that invents agents is a bug, but we prefer to run
        the known ones rather than refuse the whole request.
        """
        by_name: dict[str, SubAgent] = {a.name: a for a in self._sub_agents}
        selected: list[SubAgent] = []
        for name in requested:
            agent = by_name.get(name)
            if agent is None:
                _log_warning(
                    "plan requested unknown Sub_Agent; skipping",
                    agent_name=name,
                )
                continue
            selected.append(agent)
        return selected

    # ------------------------------------------------------------------ #
    # Fan-out                                                            #
    # ------------------------------------------------------------------ #

    async def _fan_out(
        self,
        context: AgentContext,
        agents: Sequence[SubAgent],
    ) -> list[AgentResult]:
        """Run every Sub_Agent concurrently, subject to the concurrency cap.

        Uses :class:`asyncio.Semaphore` to bound concurrency at
        ``_concurrency_cap`` (Req 5.4). Each completion publishes a
        partial immediately — we do **not** wait for all agents to
        finish before streaming (Req 1.7).

        :func:`asyncio.gather` is called with
        ``return_exceptions=False`` because :meth:`_invoke_agent`
        already catches every exception and converts it to an
        ``AgentResult(kind="error")``. Surfacing exceptions here would
        duplicate that logic and risk a single Sub_Agent failure
        aborting the whole fan-out.
        """
        if not agents:
            return []

        semaphore = asyncio.Semaphore(self._concurrency_cap)

        async def _run_one(agent: SubAgent) -> AgentResult:
            # Semaphore blocks entry beyond the cap; publishers inside
            # ``_invoke_agent`` fire after the agent completes, not
            # after the gather returns, so the partial is visible to
            # subscribers the moment the Sub_Agent is done.
            async with semaphore:
                return await self._invoke_agent(agent, context)

        tasks = [asyncio.create_task(_run_one(agent), name=f"agent:{agent.name}") for agent in agents]
        results = list(await asyncio.gather(*tasks))

        # Prometheus: observe first-agent-partial latency (Task 20.2,
        # Req 13.2). Since all agents start simultaneously (bounded by
        # the semaphore) the minimum ``wall_time_ms`` across results
        # is a good proxy for "time to first partial" that the
        # gateway would see on the Socket.IO channel.
        successful = [r.wall_time_ms for r in results if r.wall_time_ms > 0]
        if successful:
            _safe_observe_first_agent_ms(min(successful))

        return results

    async def _invoke_agent(
        self,
        agent: SubAgent,
        context: AgentContext,
    ) -> AgentResult:
        """Call a single Sub_Agent, convert failures, publish the partial."""
        start = time.perf_counter()
        try:
            result = await agent.invoke(context)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - per-agent isolation
            _log_warning(
                "Sub_Agent raised; treating as error result",
                agent_name=agent.name,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            result = AgentResult(
                agent_name=agent.name,
                kind="error",
                reason=f"{type(exc).__name__}: {exc}",
                wall_time_ms=int((time.perf_counter() - start) * 1000),
            )

        # Backfill wall_time_ms if the Sub_Agent did not set it — so
        # the partials stream always carries a latency measurement,
        # even from stub Sub_Agents that forget the field.
        if result.wall_time_ms == 0:
            result.wall_time_ms = int((time.perf_counter() - start) * 1000)

        # Structured observability log (Req 13.5, design §15) — one
        # JSON line per Sub_Agent invocation so operators can inspect
        # the fan-out without touching the partials stream or the
        # ``research_provenance`` table. Wrapped in try/except so a
        # logger-shape mismatch cannot break the run.
        _safe_log_sub_agent_invocation(
            run_id=context.run_id,
            user_id=context.user_id,
            result=result,
        )

        # Publish the partial. The publisher is best-effort: a publish
        # failure is logged and swallowed so a broken Redis cannot
        # break the run (the final brief still lands via the gateway's
        # REST response).
        await self._publish_agent_partial(context.run_id, result)
        return result

    # ------------------------------------------------------------------ #
    # Synthesiser                                                        #
    # ------------------------------------------------------------------ #

    async def _synthesize_first_pass(
        self,
        *,
        agent_results: Sequence[AgentResult],
        symbol: str | None,
        user_prompt: str,
    ) -> Any:
        """Call the injected synthesiser with the first-pass signature."""
        return await self._synthesizer(
            agent_results=tuple(agent_results),
            symbol=symbol,
            user_prompt=user_prompt,
        )

    def _build_synthesize_fn_for_resynthesis(
        self,
        *,
        agent_results: Sequence[AgentResult],
        symbol: str | None,
        user_prompt: str,
    ) -> Callable[..., Awaitable[Any]]:
        """Return a re-synthesis-shaped callable the loop can call.

        The resynthesis loop in
        :mod:`src.research.judge.resynthesis` calls::

            synthesize_fn(
                prior_brief=..., unsupported_claims=..., numeric_findings=...
            )

        We adapt the injected synthesiser to that signature by
        forwarding ``agent_results`` / ``symbol`` / ``user_prompt``
        from the enclosing scope. The synthesiser is expected to
        accept the extra kwargs; if it does not (a minimal stub in
        tests), the closure retries with only the feedback kwargs so
        the loop stays usable against a duck-typed synthesiser.
        """

        async def _resynth(
            *,
            prior_brief: Any,
            unsupported_claims: tuple[UnsupportedClaim, ...],
            numeric_findings: tuple[UnsupportedClaim, ...],
        ) -> Any:
            try:
                return await self._synthesizer(
                    agent_results=tuple(agent_results),
                    symbol=symbol,
                    user_prompt=user_prompt,
                    prior_brief=prior_brief,
                    unsupported_claims=unsupported_claims,
                    numeric_findings=numeric_findings,
                )
            except TypeError:
                # Synthesiser stub that only accepts the feedback
                # kwargs — retry with the minimal signature. This is
                # what most unit tests exercise.
                return await self._synthesizer(
                    prior_brief=prior_brief,
                    unsupported_claims=unsupported_claims,
                    numeric_findings=numeric_findings,
                )

        return _resynth

    # ------------------------------------------------------------------ #
    # Judge + re-synthesis loop                                          #
    # ------------------------------------------------------------------ #

    async def _run_judge_and_resynth(
        self,
        *,
        first_brief: Any,
        numeric_findings: Sequence[UnsupportedClaim],
        agent_results: Sequence[AgentResult],
        symbol: str | None,
        user_prompt: str,
    ) -> ResynthesisOutcome:
        """Drive the Judge + single re-synthesis loop (design §11.2)."""
        resynth_fn = self._build_synthesize_fn_for_resynthesis(
            agent_results=agent_results,
            symbol=symbol,
            user_prompt=user_prompt,
        )
        return await run_resynthesis_loop(
            synthesize_fn=resynth_fn,
            judge_fn=self._judge_fn,
            brief=first_brief,
            numeric_findings=numeric_findings,
            min_score=self._min_score,
            max_retries=self._max_retries,
        )

    # ------------------------------------------------------------------ #
    # Final-brief assembly                                               #
    # ------------------------------------------------------------------ #

    def _assemble_final_brief(
        self,
        *,
        outcome: ResynthesisOutcome,
        agent_results: Sequence[AgentResult],
        run_id: UUID,
        symbol: str | None,
        wall_start: float,
    ) -> dict[str, Any]:
        """Build the ``ResearchBrief``-shaped dict returned by :meth:`run`.

        Task 13.8 replaces this return type with a full Pydantic
        ``ResearchBrief``. Until then, the dict carries the same
        canonical section keys (from :data:`_BRIEF_SECTIONS`) so
        swapping the return type later is a zero-change delta for
        callers.
        """
        sections = _coerce_brief_sections(outcome.brief)

        # Preserve every canonical section key, even when the
        # synthesiser skipped one — callers (renderer, persistence,
        # property tests) expect a stable shape.
        for name in _BRIEF_SECTIONS:
            sections.setdefault(name, "")

        # ``partial`` is true when any Sub_Agent errored or returned
        # no_data — Req 1.6. The quality label is separate
        # (design §11.2) and reflects the Judge verdict.
        partial = any(r.kind in ("error", "no_data") for r in agent_results)

        wall_time_ms = int((time.perf_counter() - wall_start) * 1000)

        # Prometheus observability (Task 20.2, Req 13.2). The full-
        # brief histogram gets the total wall time; the runs-total
        # counter gets incremented with the terminal status label.
        # Wrapped in try/except so a metrics failure cannot break the
        # run — observability is strictly auxiliary.
        _safe_observe_full_brief_ms(wall_time_ms)
        _safe_increment_runs_total(status="partial" if partial else "done")

        return {
            "run_id": str(run_id),
            "symbol": symbol,
            **sections,
            "citations": [
                hit.chunk.chunk_id for hit in _collect_chunks(agent_results)
            ],
            "provenance": [r.to_payload() for r in agent_results],
            "judge": outcome.judge_report.model_dump(mode="json"),
            "quality": outcome.quality,
            "unsupported_sections": sorted(outcome.unsupported_sections),
            "partial": partial,
            "wall_time_ms": wall_time_ms,
        }

    # ------------------------------------------------------------------ #
    # Partials stream publisher                                          #
    # ------------------------------------------------------------------ #

    async def _publish_agent_partial(
        self,
        run_id: UUID,
        result: AgentResult,
    ) -> None:
        """XADD a per-agent partial onto :data:`RESEARCH_PARTIALS_STREAM`."""
        await self._publish(format_agent_partial(run_id, result))

    async def _publish_done(self, *, run_id: UUID, quality: str) -> None:
        """XADD an end-of-run marker so partials-stream subscribers close cleanly."""
        await self._publish(format_done(run_id, quality=quality))

    async def _publish(self, fields: Mapping[str, Any]) -> None:
        """Best-effort publish to the partials stream.

        Publisher failures are logged and swallowed. The gateway's
        Socket.IO path is an alternate route to the client (design
        §3.12, §5.2); a broken Redis stream does not take down the
        run, it just loses visibility into the partials.
        """
        if self._partials_publisher is None:
            return
        try:
            await self._partials_publisher(RESEARCH_PARTIALS_STREAM, fields)
        except Exception as exc:  # noqa: BLE001 - best-effort
            _log_warning(
                "partials publish failed",
                error_type=type(exc).__name__,
                error=str(exc),
                stream=RESEARCH_PARTIALS_STREAM,
            )


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _collect_chunks(results: Sequence[AgentResult]) -> list[ChunkHit]:
    """Flatten every Sub_Agent's cited chunks, preserving order.

    ``list.extend`` rather than a set so duplicates (legitimate when
    two Sub_Agents cite the same chunk) are retained for the numeric
    validator — the validator does a ``for chunk in cited_chunks``
    token extraction that is not de-duplicated.
    """
    flat: list[ChunkHit] = []
    for r in results:
        flat.extend(r.chunks)
    return flat


def _coerce_brief_sections(
    brief: Mapping[str, str] | object,
) -> dict[str, str]:
    """Normalise a brief (mapping or object) to ``{section_name: content}``.

    Mirrors the coercion in
    :func:`src.research.validators.numeric_validator._coerce_brief_sections`
    — any drift between the two would make the Orchestrator's final
    shape diverge from what the numeric validator inspected.
    """
    if isinstance(brief, Mapping):
        return {
            str(name): "" if content is None else str(content)
            for name, content in brief.items()
        }
    coerced: dict[str, str] = {}
    for name in _BRIEF_SECTIONS:
        value = getattr(brief, name, None)
        if isinstance(value, str):
            coerced[name] = value
    return coerced


def _log_warning(message: str, **fields: Any) -> None:
    """Emit a WARNING log, adapting to the available logger shape."""
    try:
        _logger.warning(message, extra=fields)
    except TypeError:  # pragma: no cover - very old logger variants
        _logger.warning("%s %s", message, fields)


# --------------------------------------------------------------------------- #
# Safe structured-log wrappers (Task 20.1)                                    #
# --------------------------------------------------------------------------- #
#
# ``log_sub_agent_invocation`` / ``log_orchestrator_event`` live in
# :mod:`src.research.agents.logging`. The helpers below wrap them in a
# try/except so a logger failure cannot break a ``Research_Run`` —
# observability is strictly an auxiliary concern. Any exception is
# downgraded to a WARNING on the local logger so the problem is still
# visible without propagating.


def _safe_log_sub_agent_invocation(
    *,
    run_id: UUID,
    user_id: UUID,
    result: AgentResult,
) -> None:
    """Best-effort :func:`log_sub_agent_invocation` call."""
    try:
        log_sub_agent_invocation(
            run_id=run_id,
            user_id=user_id,
            agent_name=result.agent_name,
            kind=result.kind,
            section_name=result.section_name,
            wall_time_ms=result.wall_time_ms,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            reason=result.reason,
        )
    except Exception as exc:  # noqa: BLE001 - best-effort observability
        _log_warning(
            "sub_agent_invocation log emission failed",
            agent_name=result.agent_name,
            error_type=type(exc).__name__,
            error=str(exc),
        )


def _safe_log_orchestrator_event(
    *,
    run_id: UUID,
    user_id: UUID,
    event: str,
    **fields: Any,
) -> None:
    """Best-effort :func:`log_orchestrator_event` call."""
    try:
        log_orchestrator_event(
            run_id=run_id,
            user_id=user_id,
            event=event,
            **fields,
        )
    except Exception as exc:  # noqa: BLE001 - best-effort observability
        _log_warning(
            "orchestrator_event log emission failed",
            event=event,
            error_type=type(exc).__name__,
            error=str(exc),
        )


# --------------------------------------------------------------------------- #
# Safe Prometheus metric wrappers (Task 20.2)                                 #
# --------------------------------------------------------------------------- #
#
# Every call site imports the metric module lazily so a trimmed test
# install without ``prometheus_client`` (not the reference install, but
# a future contributor working in a minimal venv) does not break the
# Orchestrator's import graph. Any failure is swallowed — metrics are
# strictly auxiliary.


def _safe_observe_full_brief_ms(wall_time_ms: int) -> None:
    """Observe :data:`research_full_brief_ms` without failing the run."""
    try:
        from src.research.observability.metrics import research_full_brief_ms

        research_full_brief_ms.observe(wall_time_ms)
    except Exception:  # noqa: BLE001 - best-effort metrics
        pass


def _safe_increment_runs_total(*, status: str) -> None:
    """Increment :data:`research_runs_total` without failing the run."""
    try:
        from src.research.observability.metrics import research_runs_total

        research_runs_total.labels(status=status).inc()
    except Exception:  # noqa: BLE001 - best-effort metrics
        pass


def _safe_observe_first_agent_ms(wall_time_ms: int) -> None:
    """Observe :data:`research_first_agent_ms` without failing the run."""
    try:
        from src.research.observability.metrics import research_first_agent_ms

        research_first_agent_ms.observe(wall_time_ms)
    except Exception:  # noqa: BLE001 - best-effort metrics
        pass
