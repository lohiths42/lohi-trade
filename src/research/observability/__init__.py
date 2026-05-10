"""Observability package for Lohi-Research (Phase 18).

Exposes the Prometheus metrics surface (Task 20.2) via a flat import.

Satisfies: Req 13.2, Req 15.9
Design: §15
"""

from src.research.observability.metrics import (
    render_metrics,
    research_first_agent_ms,
    research_first_token_ms,
    research_full_brief_ms,
    research_guardrail_blocks_total,
    research_guardrail_overhead_ms,
    research_judge_failures_total,
    research_runs_total,
    reset_metrics_registry,
)

__all__ = [
    "render_metrics",
    "research_first_agent_ms",
    "research_first_token_ms",
    "research_full_brief_ms",
    "research_guardrail_blocks_total",
    "research_guardrail_overhead_ms",
    "research_judge_failures_total",
    "research_runs_total",
    "reset_metrics_registry",
]
