"""Judge_LLM — post-synthesis grounding and safety scorer (design §3.7).

Scores every ``Research_Brief`` for groundedness, citation coverage,
contradictions, and off-policy content, and triggers a single re-synthesis
on failure (Req 16.12–16.19). When ``LOHI_RESEARCH_OFFLINE=true``, falls
back to a deterministic rule-based judge that returns the same
:class:`JudgeReport` shape (Req 16.22, Task 12.4).

Public surface
--------------
* :class:`JudgeReport` — structured output of a single Judge invocation
  (design §3.7).
* :class:`UnsupportedClaim` — re-exported from
  :mod:`src.research.validators.types` so callers don't have to reach
  into the validators package.
* :func:`invoke` — async entry point. Runs the Judge_LLM and returns a
  fully-populated :class:`JudgeReport`. Fail-soft: upstream errors,
  malformed JSON, and schema mismatches all reduce to a report with
  ``safe_to_display=False`` rather than raising.
* :func:`invoke_rule_based` — offline deterministic judge (design §11.4,
  Req 16.22). Same :class:`JudgeReport` shape as :func:`invoke`, minus
  the ``llm`` / ``llm_config`` parameters.
* :func:`run_resynthesis_loop` — Orchestrator-side state machine
  implementing design §11.2: Judge → optional single re-synthesis →
  redaction on terminal failure (Req 16.18, Req 16.19).
* :class:`ResynthesisOutcome` — return type of the loop: final brief,
  terminal :class:`JudgeReport`, ``quality`` label, and the set of
  sections that were redacted (if any).
* :data:`Quality` — ``Literal["high", "medium", "low"]`` label the
  Orchestrator stamps on every ``ResearchBrief``.
* :data:`INSUFFICIENT_EVIDENCE` — exact string used to redact
  unsupported sections when ``quality == "low"`` (Req 16.19).
* :func:`should_run_async` — decide whether the synchronous Judge call
  would blow the full-brief latency budget (design §11.3, Req 15.7).
* :func:`schedule_background_judge` — run the Judge on a background
  task and publish the :class:`JudgeReport` when it completes
  (design §11.3, Req 15.8).
* :func:`publish_judge_report` — low-level helper that serialises a
  report payload and publishes it on a Redis pubsub channel.
* :func:`redis_publisher_for` — build a :data:`JudgeReportPublisher`
  bound to a Redis client in one call.
* :data:`JudgeReportPublisher` — ``Callable[[str, dict], Awaitable[None]]``
  contract for publishing async-Judge reports.
"""

from src.research.judge.async_fallback import (
    JudgeReportPublisher,
    publish_judge_report,
    redis_publisher_for,
    schedule_background_judge,
    should_run_async,
)
from src.research.judge.judge import JudgeReport, UnsupportedClaim, invoke
from src.research.judge.resynthesis import (
    INSUFFICIENT_EVIDENCE,
    Quality,
    ResynthesisOutcome,
    run_resynthesis_loop,
)
from src.research.judge.rule_based import invoke_rule_based

__all__ = [
    "JudgeReport",
    "UnsupportedClaim",
    "invoke",
    "invoke_rule_based",
    "INSUFFICIENT_EVIDENCE",
    "Quality",
    "ResynthesisOutcome",
    "run_resynthesis_loop",
    "JudgeReportPublisher",
    "should_run_async",
    "schedule_background_judge",
    "publish_judge_report",
    "redis_publisher_for",
]
