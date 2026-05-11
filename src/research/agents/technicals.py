"""Technicals Sub_Agent (Task 13.5, design §3.5, Req 1.2, Req 8.4).

Consumes the Soldier's existing ``indicators`` Redis stream (Req 8.4)
instead of going through ``HybridRetriever``. The Soldier publishes
``IndicatorSet`` snapshots onto ``stream:indicators:{symbol}`` per
``src/soldier/indicator_publisher.py``; this agent reads the most
recent N of them for the run's ``symbol`` and folds them into prompt
context.

Shape of the agent
------------------
Conforms to :class:`~src.research.agents.orchestrator.SubAgent`:

* ``name = "technicals"``.
* ``async def invoke(context) -> AgentResult``.

:meth:`invoke` flow:

1. ``context.symbol is None`` → ``AgentResult(kind="no_data", …)``.
2. Format ``stream_name_template`` with ``symbol`` (default
   ``"indicators:{symbol}"`` to match Req 8.4's logical name; the
   production reader adapter can translate that to the real
   ``stream:indicators:{symbol}`` shape).
3. ``redis_reader.xrevrange(stream, count=N)`` → parse → filter.
   The indicators stream is sharded per symbol, so events whose
   fields dict does not carry a ``symbol`` key are still kept —
   ``filter_events_by_symbol(..., sharded_by_stream=True)`` handles
   that.
4. Empty → ``AgentResult(kind="no_data", reason="no recent indicators
   events")``. No LLM call.
5. Otherwise render ``prompts/v1/technicals_agent.md`` and call the
   LLM.
6. Return ``AgentResult(kind="ok", section_name="technical_view", …)``
   with empty ``chunks`` — same rationale as
   :class:`~src.research.agents.news_sentiment.NewsSentimentAgent`.

Section placement
-----------------
Design §3.5 assigns this agent the ``technical_view`` section of the
brief — unambiguous here because ``technical_view`` is the only
technicals-oriented section in the canonical list (Req 1.5).

Satisfies
---------
* Req 1.2 — participates in the Orchestrator fan-out.
* Req 1.3 — empty stream → ``no_data`` without an LLM call.
* Req 1.6 — LLM exceptions propagate to the Orchestrator's isolation
  wrapper.
* Req 8.4 — consumes the Soldier's ``indicators`` Redis stream.
* Req 16.6 — prompt loaded from versioned, immutable
  ``prompts/v1/technicals_agent.md``.
* design §2.1, §3.5.
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

__all__ = ["TechnicalsAgent", "build"]


# ----------------------------------------------------------------------- #
# Stream identity                                                         #
# ----------------------------------------------------------------------- #

# Template used to construct the per-symbol stream name. Req 8.4 names
# the stream ``indicators``; the Soldier publishes onto the sharded
# form ``stream:indicators:{symbol}`` (see
# ``src/soldier/indicator_publisher.py``) so the default template
# carries ``{symbol}``. Operators can override to point at a different
# stream shape in config. ``str.format(symbol=...)`` is called in
# :meth:`TechnicalsAgent._resolve_stream_name`.
_DEFAULT_STREAM_NAME_TEMPLATE: Final[str] = "indicators:{symbol}"

# Default window of recent events fetched. 20 matches the default used
# by the News_Sentiment Agent — close enough to the Soldier's 100-entry
# maxlen (``INDICATOR_STREAM_MAXLEN``) to surface a useful window
# without blowing the prompt token budget (Req 12.3).
_DEFAULT_EVENTS_COUNT: Final[int] = 20

# Prompt defaults mirror the News_Sentiment Agent and the retrieval-only
# base class. See comments there.
_REFUSAL_NO_CONTEXT: Final[str] = "INSUFFICIENT_EVIDENCE: no context available."
_DEFAULT_TEMPERATURE: Final[float] = 0.0
_DEFAULT_MAX_TOKENS: Final[int] = 2048
_PROMPT_VERSION: Final[str] = "v1"
_PROMPT_NAME: Final[str] = "technicals_agent"


@dataclass
class TechnicalsAgent:
    """Stream-consuming Sub_Agent for technical indicators (Req 8.4).

    Construction
    ------------
    ``llm`` and ``redis_reader`` are the two required dependencies
    (both accept ``None`` in the dataclass field so the concrete
    default stays readable; :meth:`invoke` raises a clear
    ``ValueError`` if either is missing at call time).

    Stream name
    -----------
    :attr:`stream_name_template` is a ``str.format``-style template
    with a ``{symbol}`` placeholder. The default
    ``"indicators:{symbol}"`` matches Req 8.4's logical name;
    operators pointing at the raw Soldier stream should override
    with ``"stream:indicators:{symbol}"``.
    """

    name: str = "technicals"
    section_name: str = "technical_view"

    llm: LLMProvider | None = None
    redis_reader: RedisStreamReader | None = None

    config: AgentConfig = field(
        default_factory=lambda: AgentConfig(
            temperature=_DEFAULT_TEMPERATURE,
            max_tokens=_DEFAULT_MAX_TOKENS,
            prompt_version=_PROMPT_VERSION,
        ),
    )

    stream_name_template: str = _DEFAULT_STREAM_NAME_TEMPLATE
    events_count: int = _DEFAULT_EVENTS_COUNT

    # ------------------------------------------------------------------ #
    # SubAgent Protocol                                                  #
    # ------------------------------------------------------------------ #

    async def invoke(self, context: AgentContext) -> AgentResult:
        """Stream pull → (maybe) LLM → :class:`AgentResult`."""
        start = time.perf_counter()

        if context.symbol is None:
            return AgentResult(
                agent_name=self.name,
                kind="no_data",
                section_name=self.section_name,
                reason=(
                    "no_data: technicals requires a symbol scope to "
                    "resolve the indicators stream name"
                ),
                wall_time_ms=int((time.perf_counter() - start) * 1000),
            )

        if self.redis_reader is None:
            raise ValueError(
                f"{self.name} agent requires a RedisStreamReader; "
                "construct with ``redis_reader=...``.",
            )

        stream_name = self._resolve_stream_name(context.symbol)
        raw_entries = await self.redis_reader.xrevrange(
            stream_name,
            count=self.events_count,
        )
        parsed = [
            parse_stream_entry(stream=stream_name, entry=entry)
            for entry in raw_entries
        ]
        # The indicators stream is sharded per symbol by name, but the
        # ``IndicatorSet`` serialisation does include ``symbol`` in the
        # fields dict (see
        # ``src/soldier/indicator_publisher.py::_serialize_indicators``),
        # so the happy path matches cleanly by ``symbol``. Passing
        # ``sharded_by_stream=True`` is belt-and-braces: if a future
        # serialiser drops the ``symbol`` key, we still keep the events
        # because the stream name carried the ticker.
        events = filter_events_by_symbol(
            parsed,
            symbol=context.symbol,
            sharded_by_stream=True,
        )

        if not events:
            return AgentResult(
                agent_name=self.name,
                kind="no_data",
                section_name=self.section_name,
                reason=(
                    f"no_data: no recent indicators events for "
                    f"symbol={context.symbol}"
                ),
                wall_time_ms=int((time.perf_counter() - start) * 1000),
            )

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
                f"{self.name} agent requires an LLMProvider; "
                "construct with ``llm=...``.",
            )
        completion = await self.llm.complete(messages, self._llm_params())

        wall_time_ms = int((time.perf_counter() - start) * 1000)

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

    def _resolve_stream_name(self, symbol: str) -> str:
        """Substitute ``{symbol}`` into :attr:`stream_name_template`.

        Guards against a template that forgot the placeholder — in
        that case every run would hit the same single stream and
        symbol scoping would silently break. We surface a clear
        :class:`ValueError` at the call site so misconfiguration
        fails loud.
        """
        if "{symbol}" not in self.stream_name_template:
            raise ValueError(
                "stream_name_template must contain '{symbol}' to enable "
                "per-symbol sharded reads; got "
                f"{self.stream_name_template!r}",
            )
        return self.stream_name_template.format(symbol=symbol)

    def _render_prompt(
        self,
        *,
        events: Iterable[StreamEvent],
        user_prompt: str,
    ) -> str:
        """Load + render the versioned technicals prompt."""
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
    """Format events for the prompt (identical layout to news_sentiment)."""
    blocks = [event.render_prompt_line() for event in events]
    if not blocks:
        return "<no cited chunks>"
    return "\n\n".join(blocks)


def build(
    llm: LLMProvider,
    redis_reader: RedisStreamReader,
    config: AgentConfig | None = None,
) -> TechnicalsAgent:
    """Convenience factory for registry-style wiring."""
    return TechnicalsAgent(
        llm=llm,
        redis_reader=redis_reader,
        config=config
        or AgentConfig(
            temperature=_DEFAULT_TEMPERATURE,
            max_tokens=_DEFAULT_MAX_TOKENS,
            prompt_version=_PROMPT_VERSION,
        ),
    )
