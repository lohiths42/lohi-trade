"""Prometheus counters + histograms for Lohi-Research (Task 20.2).

Exposes a set of module-level metric objects bound to a **private**
:class:`~prometheus_client.CollectorRegistry` so tests can reset the
registry without touching the global ``REGISTRY`` shared with the rest
of the process. The ``/api/v2/research/metrics`` endpoint (wired in
:mod:`backend-gateway.app.routers.research`) scrapes this private
registry via :func:`render_metrics`.

Satisfies
---------
* Req 13.2 — per-run and per-component metrics emitted in the
  Prometheus text format.
* Req 15.9 — latency histograms for guardrail overhead and full-brief
  latency.

Design references
-----------------
* §15 — observability topology: Prometheus metrics + structured logs.

Metric summary
--------------
Counters:
    * ``research_runs_total{status}`` — total research runs labelled by
      terminal status (``done`` / ``partial`` / ``error``).
    * ``research_guardrail_blocks_total{rule_id}`` — guardrail
      ``refuse`` / ``modify`` decisions, labelled by rule id.
    * ``research_judge_failures_total`` — Judge_LLM short-circuits
      (provider error, JSON parse error, schema error).

Histograms:
    * ``research_first_token_ms`` — latency to the first streamed token.
    * ``research_first_agent_ms`` — latency to the first Sub_Agent
      partial.
    * ``research_full_brief_ms`` — end-to-end ``Research_Run`` latency.
    * ``research_guardrail_overhead_ms`` — per-decision guardrail
      overhead.

Test seam
---------
:func:`reset_metrics_registry` swaps the module-level registry + metric
objects with fresh instances. Call it from a pytest fixture when
multiple tests exercise the same counter / histogram and need a clean
slate. The exported symbols are re-bound to the new objects so
existing imports (``from src.research.observability.metrics import
research_runs_total``) keep working after a reset.
"""

from __future__ import annotations

from typing import Any

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
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


# --------------------------------------------------------------------------- #
# Private registry                                                            #
# --------------------------------------------------------------------------- #

# A dedicated registry keeps the Lohi-Research metrics isolated from
# the rest of the gateway process. Two benefits:
#
# 1. Tests can reset only the research metrics without clobbering
#    whatever the gateway + base app have registered on the global
#    registry (``prometheus_client.REGISTRY``).
# 2. The ``/research/metrics`` endpoint scrapes only the research
#    metrics; operators who scrape the gateway's global ``/metrics``
#    endpoint (if one ever exists) do not see a duplicate.
#
# The variable is re-bound by :func:`reset_metrics_registry`; every
# metric below is re-created at that point so the tests can start from
# a clean slate without leaked samples.
_REGISTRY: CollectorRegistry = CollectorRegistry()


# --------------------------------------------------------------------------- #
# Metric objects                                                              #
# --------------------------------------------------------------------------- #
#
# Defined via a helper so :func:`reset_metrics_registry` can recreate
# them atomically. Module-level names are assigned at import time from
# the first call to :func:`_build_metrics`.


def _build_metrics(registry: CollectorRegistry) -> dict[str, Any]:
    """Construct and return every Lohi-Research metric on ``registry``.

    Returned as a dict so :func:`reset_metrics_registry` can rebind the
    module-level names in one go. Callers should not call this
    directly; they use the module-level constants.
    """
    return {
        "research_runs_total": Counter(
            "research_runs_total",
            "Total research runs by terminal status.",
            ["status"],
            registry=registry,
        ),
        "research_guardrail_blocks_total": Counter(
            "research_guardrail_blocks_total",
            "Guardrail refuse/modify decisions by rule_id.",
            ["rule_id"],
            registry=registry,
        ),
        "research_judge_failures_total": Counter(
            "research_judge_failures_total",
            "Judge_LLM short-circuits (provider / JSON / schema errors).",
            registry=registry,
        ),
        "research_first_token_ms": Histogram(
            "research_first_token_ms",
            "Latency to the first streamed token (ms).",
            buckets=(50, 100, 200, 400, 800, 1600, 3200),
            registry=registry,
        ),
        "research_first_agent_ms": Histogram(
            "research_first_agent_ms",
            "Latency to the first Sub_Agent partial (ms).",
            buckets=(100, 250, 500, 1000, 2000, 4000, 8000),
            registry=registry,
        ),
        "research_full_brief_ms": Histogram(
            "research_full_brief_ms",
            "End-to-end Research_Run latency (ms).",
            buckets=(1000, 2500, 5000, 10000, 15000, 30000, 60000),
            registry=registry,
        ),
        "research_guardrail_overhead_ms": Histogram(
            "research_guardrail_overhead_ms",
            "Per-decision guardrail overhead (ms).",
            buckets=(1, 5, 10, 25, 50, 100, 250),
            registry=registry,
        ),
    }


_metrics = _build_metrics(_REGISTRY)

research_runs_total: Counter = _metrics["research_runs_total"]
research_guardrail_blocks_total: Counter = _metrics["research_guardrail_blocks_total"]
research_judge_failures_total: Counter = _metrics["research_judge_failures_total"]
research_first_token_ms: Histogram = _metrics["research_first_token_ms"]
research_first_agent_ms: Histogram = _metrics["research_first_agent_ms"]
research_full_brief_ms: Histogram = _metrics["research_full_brief_ms"]
research_guardrail_overhead_ms: Histogram = _metrics["research_guardrail_overhead_ms"]


# --------------------------------------------------------------------------- #
# Public helpers                                                              #
# --------------------------------------------------------------------------- #


def render_metrics() -> tuple[bytes, str]:
    """Render the current Lohi-Research registry as Prometheus text.

    Returns
    -------
    tuple[bytes, str]
        ``(payload, content_type)`` — ``payload`` is the text-format
        bytes, ``content_type`` is the canonical
        ``"text/plain; version=0.0.4; charset=utf-8"`` string exposed
        by the client library as :data:`CONTENT_TYPE_LATEST`.

    The FastAPI router wires this into ``Response`` so Prometheus
    scrapes pick up the research metrics at
    ``GET /api/v2/research/metrics``.
    """
    return generate_latest(_REGISTRY), CONTENT_TYPE_LATEST


def reset_metrics_registry() -> None:
    """Rebuild the private registry and every metric on it.

    Test seam: module-level metrics accumulate state across tests
    because the registry is a shared dictionary. A pytest fixture that
    wants a clean slate calls this function at setup. After the call,
    every module-level metric name (``research_runs_total`` etc.) is
    rebound to a fresh object on a fresh :class:`CollectorRegistry`,
    so tests that ``inc()`` the counter right after a reset see a
    value of ``1`` rather than ``N + 1``.
    """
    global _REGISTRY
    global _metrics
    global research_runs_total
    global research_guardrail_blocks_total
    global research_judge_failures_total
    global research_first_token_ms
    global research_first_agent_ms
    global research_full_brief_ms
    global research_guardrail_overhead_ms

    _REGISTRY = CollectorRegistry()
    _metrics = _build_metrics(_REGISTRY)

    research_runs_total = _metrics["research_runs_total"]
    research_guardrail_blocks_total = _metrics["research_guardrail_blocks_total"]
    research_judge_failures_total = _metrics["research_judge_failures_total"]
    research_first_token_ms = _metrics["research_first_token_ms"]
    research_first_agent_ms = _metrics["research_first_agent_ms"]
    research_full_brief_ms = _metrics["research_full_brief_ms"]
    research_guardrail_overhead_ms = _metrics["research_guardrail_overhead_ms"]
