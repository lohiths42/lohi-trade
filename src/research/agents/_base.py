"""Shared retrieval + LLM plumbing for the filings / fundamentals / peer_sector / macro agents.

Design context
--------------
Design §3.5 defines six retrieval-backed Sub_Agents (Filings,
Fundamentals, News_Sentiment, Technicals, Peer_Sector, Macro) that
follow the same three-step pattern:

1. Pull per-agent chunks from the ``HybridRetriever`` under the run's
   ``(user_id, symbol)`` namespace (Req 3.10).
2. Render the agent's versioned, immutable prompt template from
   ``prompts/v1/<agent>_agent.md`` (Req 16.6, design §3.9).
3. Call the configured ``LLMProvider`` (Req 12.1 — per-agent model
   config) and return a structured :class:`AgentResult`.

News_Sentiment (Task 13.4) and Technicals (Task 13.5) additionally
consume the Commander / Soldier Redis streams, so they do not reuse
this base. The four retrieval-only agents covered by Tasks 13.2,
13.3, 13.6, and 13.7 share every line below via
:class:`BaseRetrievalAgent`.

Why a base class, not a helper function
---------------------------------------
Each concrete Sub_Agent needs two pieces of per-agent state: its
:class:`RetrievalFilter` shape (document_type narrowing, extra
keyword tags) and its prompt filename. Expressing those as class
attributes keeps the surface minimal — the concrete agent modules in
``filings.py`` / ``fundamentals.py`` / ``peer_sector.py`` /
``macro.py`` subclass once and set class-level constants. The base's
:meth:`invoke` implementation is generic and never overridden.

Failure semantics
-----------------
The base follows the contract documented in
:class:`src.research.agents.orchestrator.SubAgent`:

* Empty retrieval → :class:`AgentResult` with ``kind="no_data"``
  (Req 1.3). The LLM is **never** called; returning no_data short-
  circuits the pipeline and saves tokens.
* LLM exception → the base re-raises so the Orchestrator's
  per-agent ``try/except`` in
  :meth:`ResearchOrchestrator._invoke_agent` catches it and
  converts to ``AgentResult(kind="error", reason=…)`` (Req 1.6).
  This keeps the error-isolation story centralised in one place.
* Missing ``symbol`` — the base returns ``no_data`` rather than
  raising, matching the Orchestrator's "no symbol supplied" pattern
  documented on :meth:`ResearchOrchestrator.run`.

Satisfies
---------
* Req 1.2 — the six retrieval Sub_Agents share a uniform shape.
* Req 1.3 — no-data handling is explicit and uniform.
* Req 1.6 — exceptions propagate for Orchestrator-side isolation.
* Req 1.8 — ``input_tokens`` / ``output_tokens`` / ``wall_time_ms``
  are populated on every ok result.
* Req 12.1 — each subclass can inject its own ``LLMProvider`` and
  :class:`LLMParams`.
* Req 16.6 — versioned prompts loaded through the immutable
  :mod:`src.research.prompts.loader`.

Design references
-----------------
* §3.5 — Sub_Agent graph, no_data / error result shapes.
* §3.9 — shared prompt skeleton + placeholder contract.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Final, Iterable

from src.research.agents.orchestrator import AgentContext, AgentResult
from src.research.guardrails.refusal_policy import REFUSAL_POLICY_BLOCK
from src.research.prompts.loader import load_prompt, render
from src.research.providers.base import (
    ChunkHit,
    LLMParams,
    LLMProvider,
    Message,
    RetrievalFilter,
)

__all__ = ["BaseRetrievalAgent", "AgentConfig"]


# Canonical default for the ``{{REFUSAL_NO_CONTEXT}}`` placeholder in
# every Sub_Agent template (design §3.9). Mirrors the constant in
# :mod:`src.research.judge.judge` — kept duplicated for the same
# reason documented there: there is no shared refusal-module helper
# that owns this string yet (design §10.1 enumerates the policy text
# in ``REFUSAL_POLICY_BLOCK``; the no-context refusal is Sub_Agent-
# specific wording). The shared constant will move to a single home
# when the refusal module lands.
_REFUSAL_NO_CONTEXT: Final[str] = "INSUFFICIENT_EVIDENCE: no context available."

# Pre-fusion candidate depth handed to ``HybridRetriever.retrieve``.
# The retriever's own default ``top_k`` is 40 (see
# :class:`HybridRetriever`); keeping the base here in lockstep so
# tests and operators see the same number at both layers.
_DEFAULT_RETRIEVAL_K: Final[int] = 40

# Default LLM sampling parameters for Sub_Agent calls. Deterministic
# (temperature=0) so the Judge and property tests can reason about
# content stability. ``max_tokens=2048`` matches the Judge default
# (see :mod:`src.research.judge.judge`) and is ample for the JSON
# payloads the Sub_Agent prompts ask for.
_DEFAULT_TEMPERATURE: Final[float] = 0.0
_DEFAULT_MAX_TOKENS: Final[int] = 2048

# Prompt template version. Currently the only version shipped (see
# ``src/research/prompts/v1/``); kept as a constant so a future v2
# rollout is a single-line change in each subclass.
_PROMPT_VERSION: Final[str] = "v1"


@dataclass
class AgentConfig:
    """Per-agent knobs an operator might want to override (Req 12.1).

    Defaults mirror the design §7.1 ``research.agents.<name>.*``
    block — deterministic temperature, 2048 output cap, v1 prompts,
    pre-fusion pool of 40. A concrete Sub_Agent that needs tighter
    limits (e.g. a smaller ``max_tokens`` for a cheaper model)
    overrides fields at construction time.

    ``retrieval_k`` is the pre-fusion pool handed to the retriever;
    ``final_k`` is how many hits the Sub_Agent keeps in its
    ``AgentResult.chunks`` list. ``None`` means "keep them all".
    """

    temperature: float = _DEFAULT_TEMPERATURE
    max_tokens: int = _DEFAULT_MAX_TOKENS
    retrieval_k: int = _DEFAULT_RETRIEVAL_K
    final_k: int | None = None
    timeout_ms: int | None = None
    prompt_version: str = _PROMPT_VERSION


@dataclass
class BaseRetrievalAgent:
    """Shared implementation for retrieval-only Sub_Agents (design §3.5).

    Concrete Sub_Agents (``FilingsAgent``, ``FundamentalsAgent``,
    ``PeerSectorAgent``, ``MacroAgent``) subclass this dataclass and
    set class-level :attr:`name`, :attr:`section_name`,
    :attr:`prompt_name`, and optionally override
    :meth:`build_query` / :meth:`build_retrieval_filter`. Everything
    else — prompt rendering, no-data short-circuit, token counting,
    :class:`AgentResult` assembly — lives here.

    The class is a :class:`dataclasses.dataclass` so the concrete
    subclasses can be constructed via keyword args with readable
    defaults. It is deliberately *not* a Pydantic model: the
    ``LLMProvider`` attribute is an arbitrary Protocol implementor
    that Pydantic would reject without an arbitrary_types_allowed
    escape hatch that this module does not need.

    Parameters
    ----------
    llm:
        The :class:`LLMProvider` the Sub_Agent will call. Injected at
        construction time so tests can hand in a ``FakeLLMProvider``
        and production can hand in a registry-resolved provider per
        Req 12.1.
    config:
        Optional :class:`AgentConfig` override. Defaults to the
        shared values documented on :class:`AgentConfig`.
    """

    # Class-level identity (overridden by every concrete subclass).
    # ``name`` must match the Orchestrator's ``SubAgent`` Protocol
    # (see :class:`src.research.agents.orchestrator.SubAgent`) and
    # the ``AgentResult.agent_name`` convention (design §4.2).
    name: str = ""
    # Canonical brief section this agent primarily contributes to
    # (design §3.5). Used by the Report_Synthesizer (Task 13.8) to
    # thread content into the right brief field.
    section_name: str = ""
    # Basename of the prompt template (e.g. ``"filings_agent"``);
    # the base appends ``.md`` and loads from
    # ``src/research/prompts/<version>/``.
    prompt_name: str = ""

    # Injected at construction time.
    llm: LLMProvider | None = None
    config: AgentConfig = field(default_factory=AgentConfig)

    # ------------------------------------------------------------------ #
    # SubAgent Protocol                                                  #
    # ------------------------------------------------------------------ #

    async def invoke(self, context: AgentContext) -> AgentResult:
        """Run the three-step pattern: retrieve → (maybe) LLM → AgentResult.

        Steps
        -----
        1. Short-circuit when ``context.symbol`` is ``None`` — every
           retrieval-backed Sub_Agent requires a symbol scope to build
           the :class:`RetrievalFilter` (Req 3.10). Returns ``no_data``.
        2. Build the per-agent query and filter.
        3. Call ``context.retriever.retrieve(query, filter, k=…)``.
           Empty result → ``no_data`` (Req 1.3).
        4. Render the versioned prompt and call the LLM.
        5. Return a fully-populated :class:`AgentResult` with
           ``kind="ok"``, the cited chunks, and provenance metrics
           (Req 1.8).

        Exceptions from the retriever or the LLM bubble up to the
        Orchestrator, which converts them to ``kind="error"`` per
        Req 1.6 (see :meth:`ResearchOrchestrator._invoke_agent`).
        """
        start = time.perf_counter()

        # Step 1 — symbol scope is mandatory.
        if context.symbol is None:
            return AgentResult(
                agent_name=self.name,
                kind="no_data",
                section_name=self.section_name,
                reason=f"no_data: {self.name} requires a symbol scope",
                wall_time_ms=int((time.perf_counter() - start) * 1000),
            )

        # Step 2 — build query + filter for this agent.
        query = self.build_query(context)
        retrieval_filter = self.build_retrieval_filter(context)

        # Step 3 — retrieve. ``final_k`` caps what we keep in the
        # ``AgentResult.chunks`` list; ``retrieval_k`` is the pre-
        # fusion pool. The retriever API takes ``k`` as the output
        # depth, so we pass ``retrieval_k`` there and truncate below.
        hits = await context.retriever.retrieve(
            query,
            retrieval_filter,
            k=self.config.retrieval_k,
        )
        if not hits:
            return AgentResult(
                agent_name=self.name,
                kind="no_data",
                section_name=self.section_name,
                reason=(
                    f"no_data: no {self.name} chunks found for "
                    f"symbol={context.symbol}"
                ),
                wall_time_ms=int((time.perf_counter() - start) * 1000),
            )

        # Optionally truncate the chunk set before building the prompt.
        # Smaller prompts keep token usage predictable and let
        # per-agent ``max_tokens`` (Req 12.1) stay tight.
        if self.config.final_k is not None:
            hits = hits[: self.config.final_k]

        # Step 4 — render prompt + call LLM.
        system_prompt = self._render_prompt(
            chunks=hits,
            user_prompt=context.user_prompt,
        )
        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=context.user_prompt),
        ]
        if self.llm is None:
            # Defensive — construction-time validation would be nicer,
            # but we accept a None ``llm`` to keep the dataclass
            # constructor ergonomic (``llm=None`` is the default so
            # subclasses don't have to repeat ``llm: LLMProvider`` in
            # their own class bodies). Surfacing a clear error here
            # rather than in the LLM call path avoids a confusing
            # AttributeError on ``llm.complete``.
            raise ValueError(
                f"{self.name} agent requires an LLMProvider; "
                "construct with ``llm=...``."
            )
        completion = await self.llm.complete(messages, self._llm_params())

        wall_time_ms = int((time.perf_counter() - start) * 1000)

        # Step 5 — assemble the result. ``section_md`` carries the
        # LLM's content verbatim; Report_Synthesizer (Task 13.8)
        # will thread it into the right brief field.
        return AgentResult(
            agent_name=self.name,
            kind="ok",
            section_name=self.section_name,
            section_md=completion.content,
            chunks=list(hits),
            input_tokens=completion.input_tokens,
            output_tokens=completion.output_tokens,
            wall_time_ms=wall_time_ms,
        )

    # ------------------------------------------------------------------ #
    # Query + filter hooks                                               #
    # ------------------------------------------------------------------ #

    def build_query(self, context: AgentContext) -> str:
        """Construct the retrieval query for this agent.

        The default implementation forwards ``context.user_prompt``
        verbatim — simple and appropriate for agents whose primary
        filter is the :class:`RetrievalFilter` (e.g. ``macro``).
        Concrete subclasses that benefit from prompt shaping (e.g.
        prepending "annual report" for the fundamentals agent to
        bias BM25 toward results-oriented chunks) override this.

        Subclasses MAY consult the retrieval plan stashed on
        ``context.plan.retrieval_plan[self.name]`` — the plan node
        populates it with per-agent intents. The default falls back
        to ``user_prompt`` when no planner intent is present so the
        unit-test path (no real plan node) still produces a sensible
        query.
        """
        plan_query = context.plan.retrieval_plan.get(self.name)
        if plan_query:
            return plan_query
        return context.user_prompt

    def build_retrieval_filter(self, context: AgentContext) -> RetrievalFilter:
        """Build the per-agent :class:`RetrievalFilter` (Req 3.10, design §3.3).

        Default: scope on ``(user_id, symbol)`` only. Subclasses that
        want to narrow by ``document_type`` override this — e.g.
        :class:`FilingsAgent` narrows to ``announcement`` / etc.

        Note: the production Chroma / pgvector / Qdrant / LanceDB
        adapters **do not** apply ``document_type`` to the filter
        (see ``src/research/providers/vector_store/chroma.py`` module
        docstring) because ``ChunkRecord`` doesn't carry
        ``document_type`` — it lives on the parent document row.
        The filter field is kept so the narrowing *intent* is visible
        in the trace and the Judge can inspect it; a future task
        that copies ``document_type`` down to chunk metadata will
        light up the actual narrowing.
        """
        return RetrievalFilter(
            user_id=context.user_id,
            symbol=context.symbol,
        )

    # ------------------------------------------------------------------ #
    # Prompt rendering                                                   #
    # ------------------------------------------------------------------ #

    def _render_prompt(
        self,
        *,
        chunks: Iterable[ChunkHit],
        user_prompt: str,
    ) -> str:
        """Load and render the versioned agent prompt (Req 16.6, design §3.9).

        Substitutes the four shared-skeleton placeholders:

        * ``{{REFUSAL_NO_CONTEXT}}`` — the exact-string refusal when
          context is empty (not reached here because empty-chunks
          short-circuits to ``no_data`` before the prompt is
          rendered, but the placeholder must still be substituted to
          satisfy the loader's fail-loud contract).
        * ``{{REFUSAL_POLICY_BLOCK}}`` — the canonical refusal policy
          text from :data:`REFUSAL_POLICY_BLOCK`.
        * ``{{RETRIEVED_CHUNKS_VERBATIM}}`` — the formatted chunks
          produced by :func:`_format_chunks`.
        * ``{{USER_PROMPT}}`` — the caller's prompt, unmodified.
        """
        prompt = load_prompt(self.config.prompt_version, self.prompt_name)
        chunks_block = _format_chunks(chunks)
        return render(
            prompt,
            substitutions={
                "REFUSAL_NO_CONTEXT": _REFUSAL_NO_CONTEXT,
                "REFUSAL_POLICY_BLOCK": REFUSAL_POLICY_BLOCK,
                "RETRIEVED_CHUNKS_VERBATIM": chunks_block,
                "USER_PROMPT": user_prompt,
            },
        )

    # ------------------------------------------------------------------ #
    # LLM params                                                         #
    # ------------------------------------------------------------------ #

    def _llm_params(self) -> LLMParams:
        """Build :class:`LLMParams` from the agent's :class:`AgentConfig`.

        Per-agent overrides come from :attr:`config`; global defaults
        come from :class:`AgentConfig`. ``stream`` is always ``False``
        here — streaming from Sub_Agents is Task 13.10 territory.
        """
        kwargs: dict[str, Any] = {
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "stream": False,
        }
        if self.config.timeout_ms is not None:
            kwargs["timeout_ms"] = self.config.timeout_ms
        return LLMParams(**kwargs)


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _format_chunks(chunks: Iterable[ChunkHit]) -> str:
    """Format chunks as ``# <chunk_id>\\n<text>`` blocks for the prompt.

    Identical layout to :func:`src.research.judge.judge._format_chunks`
    so the Sub_Agent and the Judge read the same chunk syntax — a
    Sub_Agent's ``[cite:<chunk_id>]`` references always match
    exactly one ``# <chunk_id>`` heading the Judge will see.

    An empty iterable returns ``"<no cited chunks>"`` — the base's
    :meth:`BaseRetrievalAgent.invoke` guards against that path by
    short-circuiting to ``no_data`` before rendering, so the
    placeholder is only ever emitted by callers that bypass the
    guard (e.g. tests that render in isolation).
    """
    blocks: list[str] = []
    for hit in chunks:
        chunk = hit.chunk
        blocks.append(f"# {chunk.chunk_id}\n{chunk.text}")
    if not blocks:
        return "<no cited chunks>"
    return "\n\n".join(blocks)
