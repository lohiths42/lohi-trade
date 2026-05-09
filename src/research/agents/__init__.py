"""Orchestrator and seven Sub_Agents (design §3.5).

Hosts the LangGraph-based Orchestrator that plans, fans out to Sub_Agents
(Filings, Fundamentals, News_Sentiment, Technicals, Peer_Sector, Macro,
Report_Synthesizer), collects partial results with a configurable
concurrency cap, and emits a single cited `Research_Brief` per run
(Req 1.1–1.8). Per-agent LLM provider, model, temperature, max_tokens, and
timeout_ms are independently configurable (Req 12.1–12.2).

Cross-cutting run-scoped collaborators live alongside the agents:

* :class:`TokenBudget` (Task 13.9) — central per-run token tracker
  (32 000 input / 8 000 output default, Req 12.3) that the
  Orchestrator consults between fan-out steps. On overrun the
  Orchestrator halts further Sub_Agent calls and marks the brief
  ``budget_exhausted=true`` (Req 12.4).
* :class:`UsageWriter` / :class:`NoopUsageWriter` (Task 13.9) — one
  row per provider call written to ``llm_usage`` (Req 12.5). The
  no-op variant is the default injection in tests that do not need
  a DB.

These collaborators are re-exported here so callers (the Orchestrator
wiring, integration tests, future gateway code) have a single import
site. Integration is deliberately **lazy / injected** — this module
does not wire the budget tracker or the writer into the Orchestrator;
Task 13.1 keeps the Orchestrator as a structural skeleton, and a
later task will thread them in.
"""

from src.research.agents._base import AgentConfig, BaseRetrievalAgent
from src.research.agents.budget import (
    DEFAULT_INPUT_LIMIT,
    DEFAULT_OUTPUT_LIMIT,
    BudgetTotals,
    TokenBudget,
)
from src.research.agents.filings import FilingsAgent
from src.research.agents.fundamentals import FundamentalsAgent
from src.research.agents.macro import MacroAgent
from src.research.agents.news_sentiment import NewsSentimentAgent
from src.research.agents.partials import (
    EVENT_AGENT_DONE,
    EVENT_DONE,
    EVENT_TOKEN,
    NoopPartialsPublisher,
    PartialsPublisher,
    RedisPartialsPublisher,
    format_agent_partial,
    format_done,
    make_redis_partials_publisher,
)
from src.research.agents.peer_sector import PeerSectorAgent
from src.research.agents.technicals import TechnicalsAgent
from src.research.agents.usage_writer import (
    NoopUsageWriter,
    UsageWriter,
    UsageWriterProtocol,
)

__all__ = [
    "AgentConfig",
    "BaseRetrievalAgent",
    "BudgetTotals",
    "DEFAULT_INPUT_LIMIT",
    "DEFAULT_OUTPUT_LIMIT",
    "EVENT_AGENT_DONE",
    "EVENT_DONE",
    "EVENT_TOKEN",
    "FilingsAgent",
    "FundamentalsAgent",
    "MacroAgent",
    "NewsSentimentAgent",
    "NoopPartialsPublisher",
    "NoopUsageWriter",
    "PartialsPublisher",
    "PeerSectorAgent",
    "RedisPartialsPublisher",
    "TechnicalsAgent",
    "TokenBudget",
    "UsageWriter",
    "UsageWriterProtocol",
    "format_agent_partial",
    "format_done",
    "make_redis_partials_publisher",
]
