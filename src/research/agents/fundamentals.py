"""Fundamentals Sub_Agent (Task 13.3, design §3.5).

Retrieves chunks from annual reports and quarterly results and asks
the configured LLM to extract metrics, ratios, and management
commentary with ``[cite:<chunk_id>]`` markers. The agent's JSON output
(defined in ``prompts/v1/fundamentals_agent.md``) feeds into the
brief's ``financial_highlights`` section via the Report_Synthesizer
(Task 13.8, design §3.5).

Retrieval shape
---------------
Fundamentals queries target a narrower slice of the corpus than
``filings``: only ``annual_report`` and ``concall`` document types
are genuinely useful here, and occasionally quarterly results
(classified as ``announcement`` with a "quarterly_result" section
tag). The :class:`RetrievalFilter` carries ``annual_report`` as the
filter's single ``document_type`` value to make the narrowing intent
explicit in the run trace — the production vector-store adapters
currently ignore the field (see
``src/research/providers/vector_store/chroma.py`` module docstring)
so the BM25 lexical pass does most of the work today; the filter
preps the code for a future chunk-side ``document_type``.

The default query builder mixes in the tokens "financial results
revenue EBITDA margin EPS" so BM25 biases toward results-oriented
chunks even when the user prompt is short. The planner-supplied
intent on ``context.plan.retrieval_plan["fundamentals"]`` wins if
set — the same pattern every retrieval-only Sub_Agent uses.

Satisfies
---------
* Req 1.2 — fundamentals Sub_Agent participates in the fan-out.
* design §3.5 — Sub_Agent graph.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.research.agents._base import AgentConfig, BaseRetrievalAgent
from src.research.agents.orchestrator import AgentContext
from src.research.providers.base import LLMProvider, RetrievalFilter

__all__ = ["FundamentalsAgent"]


# Dominant document type for fundamentals retrieval. ``annual_report``
# is the canonical target; quarterly results are classified as
# ``announcement`` with a section tag and are picked up by the BM25
# lexical pass via the query-bias tokens below.
_FUNDAMENTALS_DOCUMENT_TYPE: str = "annual_report"

# Lexical-bias tokens prepended to the query when the user prompt is
# short or generic. Kept short so they don't overwhelm the signal in
# a detailed user prompt; BM25 picks them up cheaply for free.
_FUNDAMENTALS_QUERY_BIAS: str = "financial results revenue EBITDA margin EPS"


@dataclass
class FundamentalsAgent(BaseRetrievalAgent):
    """Retrieves fundamentals chunks and generates the fundamentals section.

    See :mod:`src.research.agents._base` for the shared contract:
    retrieve → (maybe) LLM → :class:`AgentResult`, with no-data
    short-circuit and LLM-error propagation.

    Concrete overrides
    ------------------
    * :attr:`prompt_name` → ``"fundamentals_agent"``.
    * :meth:`build_query` — prepends a lexical bias toward
      results-oriented vocabulary.
    * :meth:`build_retrieval_filter` — narrows by ``annual_report``
      document type (informational for now — see module docstring).
    """

    name: str = "fundamentals"
    section_name: str = "financial_highlights"
    prompt_name: str = "fundamentals_agent"

    def build_query(self, context: AgentContext) -> str:
        """Compose a fundamentals-biased retrieval query.

        The planner's retrieval intent (if any) wins because it will
        have been produced by the plan node with full knowledge of
        the user prompt. Otherwise the user prompt is preserved
        verbatim and the bias tokens are appended so BM25 picks up
        the fundamentals vocabulary without a generic prompt losing
        its meaning.
        """
        plan_query = context.plan.retrieval_plan.get(self.name)
        if plan_query:
            return plan_query
        user_prompt = context.user_prompt or ""
        return (
            f"{user_prompt} {_FUNDAMENTALS_QUERY_BIAS}".strip()
            if user_prompt
            else _FUNDAMENTALS_QUERY_BIAS
        )

    def build_retrieval_filter(self, context: AgentContext) -> RetrievalFilter:
        """Narrow the retrieval filter to fundamentals document types."""
        return RetrievalFilter(
            user_id=context.user_id,
            symbol=context.symbol,
            document_type=_FUNDAMENTALS_DOCUMENT_TYPE,
        )


def build(
    llm: LLMProvider,
    config: AgentConfig | None = None,
) -> FundamentalsAgent:
    """Convenience factory for registry-style wiring."""
    return FundamentalsAgent(llm=llm, config=config or AgentConfig())
