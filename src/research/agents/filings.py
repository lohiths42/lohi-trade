"""Filings Sub_Agent (Task 13.2, design §3.5).

Retrieves chunks from corporate filings (BSE / NSE announcements,
annual reports, quarterly results, SEBI EDIFAR disclosures, IR decks,
user uploads) and asks the configured LLM to summarise findings with
``[cite:<chunk_id>]`` markers.

Per design §3.5 the Report_Synthesizer consumes this agent's
:class:`AgentResult` and does **not** issue its own retrieval calls
(Req 1.4); every filings-side chunk therefore enters the brief only
through this module.

Retrieval shape
---------------
Filings-oriented queries benefit from a light lexical bias toward the
filings vocabulary ("filing", "announcement", "disclosure", …). BM25
picks these tokens up for free when they appear in the user prompt;
when the user prompt is short or generic, the agent falls back to
the planner-supplied intent stashed on
``context.plan.retrieval_plan["filings"]``.

The :class:`RetrievalFilter` narrows by the four filings-flavoured
``document_type`` values that :class:`CanonicalDoc` recognises —
``announcement``, ``annual_report``, ``concall``, ``shareholding``.
The production vector-store adapters currently ignore the
``document_type`` filter (see
``src/research/providers/vector_store/chroma.py`` module docstring
for the rationale — ``document_type`` lives on the parent document
row, not on the chunk), but the filter still surfaces the narrowing
**intent** in the run trace and it preps the code for a future task
that copies ``document_type`` down to chunk metadata. Because the
vector-store's :class:`RetrievalFilter` schema only accepts a single
``document_type`` string, this agent passes the canonical token
``"announcement"`` — the dominant document type for BSE/NSE filings —
and lets the run trace (plus the BM25 lexical pass) carry the
broader intent.

Satisfies
---------
* Req 1.2 — filings Sub_Agent participates in the fan-out.
* Req 1.3 — no-data handling delegated to :class:`BaseRetrievalAgent`.
* Req 1.6 — exceptions propagate to the Orchestrator.
* Req 12.1 — per-agent LLM + config injected at construction.
* design §3.5 — Sub_Agent graph.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.research.agents._base import AgentConfig, BaseRetrievalAgent
from src.research.agents.orchestrator import AgentContext
from src.research.providers.base import LLMProvider, RetrievalFilter

__all__ = ["FilingsAgent"]


# Document type the Filings Agent surfaces in its :class:`RetrievalFilter`.
# ``announcement`` is the dominant category for BSE/NSE feeds and
# user-uploaded filings; the vector-store adapters currently ignore
# the field (see module docstring) so the value is informational for
# now and will matter once chunks carry ``document_type`` down.
_FILINGS_DOCUMENT_TYPE: str = "announcement"


@dataclass
class FilingsAgent(BaseRetrievalAgent):
    """Retrieves filings chunks and generates the filings section.

    Construction
    ------------
    ``llm`` is the only required positional kwarg; everything else
    has a shared-default on the base. Production wiring injects an
    :class:`LLMProvider` resolved from
    ``research.agents.filings.llm_provider`` (Req 12.1 / design §7.1);
    tests inject :class:`FakeLLMProvider` to keep the path mock-free.

    Subclassing rationale
    ---------------------
    Only two hooks differ from the shared base:

    * :attr:`prompt_name` — ``"filings_agent"`` → loads
      ``prompts/v1/filings_agent.md``.
    * :meth:`build_retrieval_filter` — narrows by the filings
      ``document_type`` value.

    Everything else (prompt rendering, no-data short-circuit, token
    counting, AgentResult assembly) is identical to the other three
    retrieval-only Sub_Agents and lives in
    :class:`BaseRetrievalAgent`.
    """

    name: str = "filings"
    # The Filings Agent surfaces evidence about what the company said
    # in its own disclosures. That content fits the canonical
    # ``management_commentary`` section of the brief (design §3.5 /
    # Req 1.5); the Report_Synthesizer in Task 13.8 will thread it
    # there via ``AgentResult.section_name``.
    section_name: str = "management_commentary"
    prompt_name: str = "filings_agent"

    def build_retrieval_filter(self, context: AgentContext) -> RetrievalFilter:
        """Narrow the retrieval filter to filings document types.

        Overrides the base's user+symbol-only filter so the run
        trace makes the filings narrowing explicit. The production
        vector-store adapters currently ignore ``document_type`` —
        see the module docstring — but the field still informs the
        Judge's provenance check and any future chunk-side
        ``document_type`` narrowing.
        """
        return RetrievalFilter(
            user_id=context.user_id,
            symbol=context.symbol,
            document_type=_FILINGS_DOCUMENT_TYPE,
        )


def build(llm: LLMProvider, config: AgentConfig | None = None) -> FilingsAgent:
    """Convenience factory for registry-style wiring.

    Mirrors the ``build(cfg)`` pattern used by the provider adapters
    (see ``src/research/providers/registry.py``) so a future agent
    registry can construct Sub_Agents uniformly.
    """
    return FilingsAgent(llm=llm, config=config or AgentConfig())
