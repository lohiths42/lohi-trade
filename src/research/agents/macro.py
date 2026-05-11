"""Macro Sub_Agent (Task 13.7, design §3.5).

Retrieves macro chunks (inflation, rates, FX, commodities, policy) and
asks the configured LLM to extract observed macro factors with
``[cite:<chunk_id>]`` markers. The agent's JSON output (defined in
``prompts/v1/macro_agent.md``) feeds into the brief's ``macro_context``
section via the Report_Synthesizer (Task 13.8, design §3.5).

Retrieval shape
---------------
Macro evidence is corpus-wide: annual reports discuss commodity
exposure, announcements mention policy impacts, concall transcripts
are where management talks about the rate environment. The agent
therefore does **not** narrow by ``document_type`` for the same
reason :class:`PeerSectorAgent` does not. The BM25 lexical pass does
the heavy lifting via macro-bias tokens ("inflation rates FX
commodity policy").

The planner-supplied intent on
``context.plan.retrieval_plan["macro"]`` wins when set.

Satisfies
---------
* Req 1.2 — macro Sub_Agent participates in the fan-out.
* design §3.5 — Sub_Agent graph.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.research.agents._base import AgentConfig, BaseRetrievalAgent
from src.research.agents.orchestrator import AgentContext
from src.research.providers.base import LLMProvider

__all__ = ["MacroAgent"]


# Lexical-bias tokens for BM25. Cover the five macro factor categories
# enumerated in ``prompts/v1/macro_agent.md`` ("inflation|rates|fx|
# commodity|policy|other") so the retriever surfaces chunks that name
# any of them.
_MACRO_QUERY_BIAS: str = "inflation rates FX commodity policy"


@dataclass
class MacroAgent(BaseRetrievalAgent):
    """Retrieves macro chunks and generates the macro_context section.

    Concrete overrides
    ------------------
    * :attr:`prompt_name` → ``"macro_agent"``.
    * :meth:`build_query` — prepends macro bias tokens.
    """

    name: str = "macro"
    section_name: str = "macro_context"
    prompt_name: str = "macro_agent"

    def build_query(self, context: AgentContext) -> str:
        """Compose a macro-biased retrieval query.

        Pattern identical to :meth:`FundamentalsAgent.build_query` and
        :meth:`PeerSectorAgent.build_query` — planner intent wins,
        otherwise bias tokens are appended to the user prompt.
        """
        plan_query = context.plan.retrieval_plan.get(self.name)
        if plan_query:
            return plan_query
        user_prompt = context.user_prompt or ""
        return (
            f"{user_prompt} {_MACRO_QUERY_BIAS}".strip()
            if user_prompt
            else _MACRO_QUERY_BIAS
        )


def build(llm: LLMProvider, config: AgentConfig | None = None) -> MacroAgent:
    """Convenience factory for registry-style wiring."""
    return MacroAgent(llm=llm, config=config or AgentConfig())
