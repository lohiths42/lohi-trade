"""Peer_Sector Sub_Agent (Task 13.6, design §3.5).

Retrieves peer / sector chunks and asks the configured LLM to extract
sector labels, peer relations, and short comparisons with
``[cite:<chunk_id>]`` markers. The agent's JSON output (defined in
``prompts/v1/peer_sector_agent.md``) feeds into the brief's ``peers``
section via the Report_Synthesizer (Task 13.8, design §3.5).

Retrieval shape
---------------
Peer / sector evidence lives across the whole corpus: annual reports
call out competitors and sector classifications, announcements
reference supplier / customer relationships, and concall transcripts
carry the most candid comparisons. This agent therefore does **not**
narrow by ``document_type`` — doing so would miss genuinely relevant
chunks. The BM25 lexical pass does the heavy lifting here via the
query-bias tokens ("peers competitors sector industry").

The planner-supplied intent on
``context.plan.retrieval_plan["peer_sector"]`` wins when set —
identical pattern to the other retrieval-only Sub_Agents.

Satisfies
---------
* Req 1.2 — peer_sector Sub_Agent participates in the fan-out.
* design §3.5 — Sub_Agent graph.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.research.agents._base import AgentConfig, BaseRetrievalAgent
from src.research.agents.orchestrator import AgentContext
from src.research.providers.base import LLMProvider

__all__ = ["PeerSectorAgent"]


# Lexical-bias tokens for BM25. Kept short and generic so they apply
# across sectors; more specific terms (e.g. "bank", "pharma") would
# depend on the symbol and are better injected by the planner.
_PEER_SECTOR_QUERY_BIAS: str = "peers competitors sector industry"


@dataclass
class PeerSectorAgent(BaseRetrievalAgent):
    """Retrieves peer/sector chunks and generates the peers section.

    Concrete overrides
    ------------------
    * :attr:`prompt_name` → ``"peer_sector_agent"``.
    * :meth:`build_query` — prepends peer/sector bias tokens.

    No :meth:`build_retrieval_filter` override — peer / sector
    evidence spans every document type, so the shared user+symbol
    filter is correct.
    """

    name: str = "peer_sector"
    section_name: str = "peers"
    prompt_name: str = "peer_sector_agent"

    def build_query(self, context: AgentContext) -> str:
        """Compose a peer/sector-biased retrieval query.

        See :meth:`FundamentalsAgent.build_query` for the pattern:
        planner intent wins, otherwise bias tokens are appended.
        """
        plan_query = context.plan.retrieval_plan.get(self.name)
        if plan_query:
            return plan_query
        user_prompt = context.user_prompt or ""
        return (
            f"{user_prompt} {_PEER_SECTOR_QUERY_BIAS}".strip()
            if user_prompt
            else _PEER_SECTOR_QUERY_BIAS
        )


def build(
    llm: LLMProvider, config: AgentConfig | None = None
) -> PeerSectorAgent:
    """Convenience factory for registry-style wiring."""
    return PeerSectorAgent(llm=llm, config=config or AgentConfig())
