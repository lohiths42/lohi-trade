"""News_Sentiment Sub_Agent (Task 13.4, design §3.5, Req 1.2, Req 8.3).

Unlike the retrieval-only Sub_Agents (Filings, Fundamentals, Peer_Sector,
Macro), this agent does **not** go through ``HybridRetriever``. It reads
the Commander's existing Redis streams — ``news_clean``, ``sentiment``,
and ``bias`` (Req 8.3) — and folds the most recent events for the run's
``symbol`` directly into its prompt context. The spec is explicit that
this agent "does not re-ingest news" (Task 13.4): the Commander already
covers the scrape/classify path, so adding another retrieval pipeline
over the same data would duplicate effort and drift from ground truth.

Shape of the agent
------------------
The agent still conforms to
:class:`~src.research.agents.orchestrator.SubAgent`:

* ``name = "news_sentiment"``.
* ``async def invoke(context) -> AgentResult``.

The difference is what happens inside :meth:`invoke`:

1. If ``context.symbol`` is ``None`` → return ``AgentResult(kind="no_data",
   reason="…")``. Same short-circuit every symbol-scoped agent uses
   (matches :class:`BaseRetrievalAgent`).
2. For each configured stream, call
   ``redis_reader.xrevrange(stream, count=N)`` to pull the most recent
   N events; parse each entry into a :class:`StreamEvent`; filter by
   ``symbol``. Default ``N=20`` per stream per Task 13.4's note.
3. If the aggregate event set is empty → ``AgentResult(kind="no_data",
   reason="no recent <streams> events")``. No LLM call.
4. Otherwise render the versioned ``prompts/v1/news_sentiment_agent.md``
   template with the events formatted into ``{{RETRIEVED_CHUNKS_VERBATIM}}``
   and call the configured LLM.
5. Return ``AgentResult(kind="ok", section_name="summary", section_md=…,
   chunks=[], input_tokens=…, output_tokens=…)``. ``chunks`` stays
   empty — design §3.3's ``ChunkRecord`` shape carries ``document_id``
   / ``embedding`` fields that Redis Stream events don't have, and
   per the task brief "stream events are treated as synthetic chunks
   for provenance purposes" via their event_ids inside ``section_md``
   rather than through the structured chunks list.

Section placement
-----------------
Design §3.5 enumerates the canonical brief sections but does not
explicitly pin News_Sentiment to one. The prompt's output schema —
``headlines`` / ``themes`` / ``sentiment_summary`` — is exactly what the
``summary`` brief section carries at the top of the brief, so the
agent's ``section_name`` is ``"summary"``. The Report_Synthesizer
(Task 13.8) will thread this into the ``summary`` field of the
``ResearchBrief`` Pydantic model; if a future task decides the content
is a better fit for ``thesis`` or ``risks``, the change is a single
constant here.

Stream shapes (verbatim from the Commander, Req 8.3 / design §2.1)
-------------------------------------------------------------------
The real Commander publishers emit slightly different keys per stream
(``ticker`` vs ``symbol``, different timestamp field names); the
:mod:`src.research.agents._stream` helpers normalise those into the
:class:`StreamEvent` shape so this agent doesn't need per-stream
special cases.

Satisfies
---------
* Req 1.2 — participates in the Orchestrator fan-out.
* Req 1.3 — empty stream → ``no_data`` without an LLM call.
* Req 1.6 — LLM exceptions propagate to the Orchestrator's isolation
  wrapper.
* Req 8.3 — consumes the Commander's ``news_clean`` / ``sentiment`` /
  ``bias`` streams; does not re-ingest.
* Req 16.6 — prompt loaded from versioned, immutable
  ``prompts/v1/news_sentiment_agent.md``.
* design §2.1, §3.5 — Sub_Agent graph.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Final

from src.research.agents._base import AgentConfig
from src.research.agents._stream import (
    RedisStreamReader,
    StreamEvent,
    filter_events_by_symbol,
    parse_stream_entry,
)
from src.research.agents.orchestrator import AgentContext, AgentResult
from src.research.guardrails.refusal_policy import REFUSAL_POLICY_BLOCK
from src.research.prompts.loader import load_prompt, render
from src.research.providers.base import LLMParams, LLMProvider, Message

__all__ = ["NewsSentimentAgent", "build"]


# ----------------------------------------------------------------------- #
# Stream identities                                                       #
# ----------------------------------------------------------------------- #

# Stream names as enumerated in Req 8.3 (logical names used in the
# requirements / design). Operators can override each one via
# :class:`NewsSentimentAgent`'s constructor. The real Commander
# publishers currently emit onto ``stream:news`` / ``stream:sentiment``
# / ``stream:bias:{ticker}`` (see ``src/commander/news_publisher.py``,
# ``src/commander/sentiment_analyzer.py``, ``src/commander/bias_scheduler.py``);
# wiring that translates those into the logical names lives outside
# this agent (typically in the gateway / worker that constructs the
# ``RedisStreamReader`` adapter) so this file stays focused on the
# agent-level semantics.
_DEFAULT_NEWS_CLEAN_STREAM: Final[str] = "news_clean"
_DEFAULT_SENTIMENT_STREAM: Final[str] = "sentiment"
_DEFAULT_BIAS_STREAM: Final[str] = "bias"

# Default window of recent events fetched per stream. Matches the
# hint from Task 13.4 ("Fetch recent events — e.g., last 20 per
# stream"). Keeping the default small keeps the prompt token count
# predictable; the News_Sentiment Agent already competes with the
# retrieval-only agents for the per-run token budget (Req 12.3).
_DEFAULT_EVENTS_PER_STREAM: Final[int] = 20

# Canonical ``REFUSAL_NO_CONTEXT`` value (mirrors
# :mod:`src.research.agents._base` — same comment applies: the
# refusal-module helper doesn't yet exist, so we duplicate the
# constant here until it lands).
_REFUSAL_NO_CONTEXT: Final[str] = "INSUFFICIENT_EVIDENCE: no context available."

# LLM defaults. Deterministic temperature keeps the Judge and
# property tests stable; ``max_tokens=2048`` matches every other
# Sub_Agent (see :class:`AgentConfig`).
_DEFAULT_TEMPERATURE: Final[float] = 0.0
_DEFAULT_MAX_TOKENS: Final[int] = 2048

# Prompt version.
_PROMPT_VERSION: Final[str] = "v1"
_PROMPT_NAME: Final[str] = "news_sentiment_agent"


@dataclass
class NewsSentimentAgent:
    """Stream-consuming Sub_Agent for news + sentiment + bias (Req 8.3).

    Construction
    ------------
    ``llm`` and ``redis_reader`` are the two required dependencies —
    both are injected so unit tests can pass a
    :class:`tests.research.fakes.FakeLLMProvider` and a stub reader.
    Stream names default to the logical names from Req 8.3 but are
    overridable so operators who want to point at different streams
    (e.g. when running against a non-default Commander topology) can
    do so in config.

    SubAgent Protocol conformance
    -----------------------------
    This is a :class:`dataclasses.dataclass` so the constructor shape
    is readable; it also stores ``name`` and ``section_name`` as
    plain class-level constants so runtime ``isinstance(agent,
    SubAgent)`` checks via the Orchestrator's Protocol succeed
    without any metaclass trickery.
    """

    name: str = "news_sentiment"
    # Section the agent contributes to. The prompt's
    # ``sentiment_summary`` output is a top-of-brief summary of
    # recent news + sentiment + bias for the symbol — that maps
    # cleanly onto the brief's ``summary`` section (design §3.5).
    section_name: str = "summary"

    # Injected dependencies.
    llm: LLMProvider | None = None
    redis_reader: RedisStreamReader | None = None

    # Per-agent overrides. Defaults mirror other Sub_Agents.
    config: AgentConfig = field(
        default_factory=lambda: AgentConfig(
            temperature=_DEFAULT_TEMPERATURE,
            max_tokens=_DEFAULT_MAX_TOKENS,
            prompt_version=_PROMPT_VERSION,
        ),
    )

    # Stream-name overrides. Keep each as its own field so operators
    # can swap one stream without touching the others.
    news_clean_stream: str = _DEFAULT_NEWS_CLEAN_STREAM
    sentiment_stream: str = _DEFAULT_SENTIMENT_STREAM
    bias_stream: str = _DEFAULT_BIAS_STREAM

    # Events fetched per stream before symbol filtering.
    events_per_stream: int = _DEFAULT_EVENTS_PER_STREAM

    # ------------------------------------------------------------------ #
    # SubAgent Protocol                                                  #
    # ------------------------------------------------------------------ #

    async def invoke(self, context: AgentContext) -> AgentResult:
        """Stream pull → filter → (maybe) LLM → :class:`AgentResult`."""
        start = time.perf_counter()

        # Step 1 — symbol scope is mandatory. Without a ticker we
        # cannot filter by symbol, and the ``news_clean`` /
        # ``sentiment`` streams are global so we'd otherwise fold
        # unrelated events into the context.
        if context.symbol is None:
            return AgentResult(
                agent_name=self.name,
                kind="no_data",
                section_name=self.section_name,
                reason=(
                    "no_data: news_sentiment requires a symbol scope to " "filter stream events"
                ),
                wall_time_ms=int((time.perf_counter() - start) * 1000),
            )

        if self.redis_reader is None:
            # Symmetric with the LLM guard in :class:`BaseRetrievalAgent`
            # — construction-time validation would be tidier, but we
            # accept ``None`` so the dataclass constructor stays simple
            # and surface a clear error here rather than an
            # AttributeError deep in the stream loop.
            raise ValueError(
                f"{self.name} agent requires a RedisStreamReader; "
                "construct with ``redis_reader=...``.",
            )

        # Step 2 — fetch + parse each stream. We gather events for
        # every stream before filtering so a diagnostic can tell
        # which stream carried the hit if we ever add one.
        events: list[StreamEvent] = []
        for stream_name in self._configured_streams():
            raw_entries = await self.redis_reader.xrevrange(
                stream_name,
                count=self.events_per_stream,
            )
            parsed = [parse_stream_entry(stream=stream_name, entry=entry) for entry in raw_entries]
            # ``news_clean`` / ``sentiment`` are global streams keyed by
            # ``ticker`` in the fields dict, and ``bias`` is sometimes
            # sharded by ticker in the stream name itself (see
            # :mod:`src.commander.bias_scheduler`). Passing
            # ``sharded_by_stream=True`` keeps events whose stream name
            # already carries the ticker but whose fields dict does
            # not. Correctness is preserved because the operator is
            # expected to pass a per-symbol stream name for the sharded
            # case (e.g. ``bias:RELIANCE``) — we never keep events from
            # a mismatched sharded stream because we never asked the
            # reader for that stream.
            filtered = filter_events_by_symbol(
                parsed,
                symbol=context.symbol,
                sharded_by_stream=True,
            )
            events.extend(filtered)

        # Step 3 — empty → no_data. Never call the LLM.
        if not events:
            stream_names = ", ".join(self._configured_streams())
            return AgentResult(
                agent_name=self.name,
                kind="no_data",
                section_name=self.section_name,
                reason=(
                    f"no_data: no recent {stream_names} events " f"for symbol={context.symbol}"
                ),
                wall_time_ms=int((time.perf_counter() - start) * 1000),
            )

        # Step 4 — render prompt + call LLM.
        system_prompt = self._render_prompt(
            events=events,
            user_prompt=context.user_prompt,
        )
        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=context.user_prompt),
        ]
        if self.llm is None:
            raise ValueError(
                f"{self.name} agent requires an LLMProvider; " "construct with ``llm=...``.",
            )
        completion = await self.llm.complete(messages, self._llm_params())

        wall_time_ms = int((time.perf_counter() - start) * 1000)

        # Step 5 — assemble. ``chunks`` stays empty; provenance for
        # the Judge flows through the ``[cite:<event_id>]`` markers
        # the LLM embeds in ``section_md``. The Judge's chunk
        # resolution (design §11) is therefore a no-op for this
        # agent's citations — a future hardening task can copy event
        # ids into a ``synthetic_chunks`` list so the citation
        # validator (:mod:`src.research.validators.citation_validator`)
        # can resolve them through the vector store too. For now the
        # prompt's "Cite every non-boilerplate sentence with
        # [cite:<chunk_id>]" instruction produces event-id citations
        # that readers (human and Judge) can still cross-reference
        # against the rendered context.
        return AgentResult(
            agent_name=self.name,
            kind="ok",
            section_name=self.section_name,
            section_md=completion.content,
            chunks=[],
            input_tokens=completion.input_tokens,
            output_tokens=completion.output_tokens,
            wall_time_ms=wall_time_ms,
        )

    # ------------------------------------------------------------------ #
    # Helpers                                                            #
    # ------------------------------------------------------------------ #

    def _configured_streams(self) -> tuple[str, str, str]:
        """Return the three configured stream names in a stable order."""
        return (
            self.news_clean_stream,
            self.sentiment_stream,
            self.bias_stream,
        )

    def _render_prompt(
        self,
        *,
        events: Iterable[StreamEvent],
        user_prompt: str,
    ) -> str:
        """Load + render the versioned news_sentiment prompt.

        The same shared-skeleton placeholders that
        :class:`BaseRetrievalAgent` substitutes are applied here. The
        formatted event block goes into ``RETRIEVED_CHUNKS_VERBATIM``
        because the prompt's output schema (``headlines``, ``themes``,
        ``sentiment_summary``) references ``[cite:<chunk_id>]``; each
        event's ``event_id`` plays the role of ``chunk_id`` here.
        """
        prompt = load_prompt(self.config.prompt_version, _PROMPT_NAME)
        events_block = _format_events(events)
        return render(
            prompt,
            substitutions={
                "REFUSAL_NO_CONTEXT": _REFUSAL_NO_CONTEXT,
                "REFUSAL_POLICY_BLOCK": REFUSAL_POLICY_BLOCK,
                "RETRIEVED_CHUNKS_VERBATIM": events_block,
                "USER_PROMPT": user_prompt,
            },
        )

    def _llm_params(self) -> LLMParams:
        """Build :class:`LLMParams` from :attr:`config`."""
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


def _format_events(events: Iterable[StreamEvent]) -> str:
    """Format events as ``# <event_id>\\n…`` blocks for the prompt.

    Mirrors the ``# <chunk_id>\\n<text>`` layout that
    :func:`src.research.agents._base._format_chunks` uses so the Judge's
    ``[cite:<chunk_id>]`` grammar sees the same fence shape across
    retrieval-backed and stream-backed Sub_Agents.
    """
    blocks = [event.render_prompt_line() for event in events]
    if not blocks:
        return "<no cited chunks>"
    return "\n\n".join(blocks)


def build(
    llm: LLMProvider,
    redis_reader: RedisStreamReader,
    config: AgentConfig | None = None,
) -> NewsSentimentAgent:
    """Convenience factory mirroring the provider adapters' ``build(cfg)``."""
    return NewsSentimentAgent(
        llm=llm,
        redis_reader=redis_reader,
        config=config
        or AgentConfig(
            temperature=_DEFAULT_TEMPERATURE,
            max_tokens=_DEFAULT_MAX_TOKENS,
            prompt_version=_PROMPT_VERSION,
        ),
    )
