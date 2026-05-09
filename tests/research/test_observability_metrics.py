"""Unit tests for Phase 18 Task 20.2 — Prometheus metrics surface.

Exercises :mod:`src.research.observability.metrics` and the
``/api/v2/research/metrics`` endpoint mounted by
:mod:`backend-gateway.app.routers.research`.

Requirements: 13.2, 15.9
Design: §15
"""

from __future__ import annotations

import pytest

from src.research.observability import metrics as metrics_module
from src.research.observability.metrics import (
    render_metrics,
    reset_metrics_registry,
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _clean_registry() -> None:
    """Reset the private registry before every test.

    Prometheus counters and histograms are process-global; without a
    reset the observations from one test leak into the next. The
    :func:`reset_metrics_registry` helper rebuilds both the registry
    and every metric object in one call so the module-level symbols
    remain usable.
    """
    reset_metrics_registry()


# --------------------------------------------------------------------------- #
# Counters                                                                    #
# --------------------------------------------------------------------------- #


class TestCounters:
    def test_counter_increments(self) -> None:
        """``research_runs_total.labels(status=...).inc()`` records ≥1 sample."""
        metrics_module.research_runs_total.labels(status="done").inc()

        samples = _collect_samples(
            metrics_module.research_runs_total, name="research_runs_total"
        )
        done = [s for s in samples if s.labels.get("status") == "done"]
        assert done, "expected a sample for status=done"
        assert done[0].value >= 1

    def test_counter_separates_status_labels(self) -> None:
        metrics_module.research_runs_total.labels(status="done").inc()
        metrics_module.research_runs_total.labels(status="partial").inc()
        metrics_module.research_runs_total.labels(status="partial").inc()

        samples = _collect_samples(
            metrics_module.research_runs_total, name="research_runs_total"
        )
        by_status = {s.labels.get("status"): s.value for s in samples}
        assert by_status.get("done") == 1
        assert by_status.get("partial") == 2

    def test_judge_failures_counter_increments(self) -> None:
        metrics_module.research_judge_failures_total.inc()
        metrics_module.research_judge_failures_total.inc()

        samples = _collect_samples(
            metrics_module.research_judge_failures_total,
            name="research_judge_failures_total",
        )
        assert samples
        assert samples[0].value == 2

    def test_guardrail_blocks_counter_tracks_rule_id(self) -> None:
        metrics_module.research_guardrail_blocks_total.labels(
            rule_id="jailbreak_v1_override"
        ).inc()
        metrics_module.research_guardrail_blocks_total.labels(
            rule_id="jailbreak_v1_override"
        ).inc()
        metrics_module.research_guardrail_blocks_total.labels(
            rule_id="pii_pan"
        ).inc()

        samples = _collect_samples(
            metrics_module.research_guardrail_blocks_total,
            name="research_guardrail_blocks_total",
        )
        by_rule = {s.labels.get("rule_id"): s.value for s in samples}
        assert by_rule.get("jailbreak_v1_override") == 2
        assert by_rule.get("pii_pan") == 1


# --------------------------------------------------------------------------- #
# Histograms                                                                  #
# --------------------------------------------------------------------------- #


class TestHistograms:
    def test_histogram_observes(self) -> None:
        metrics_module.research_full_brief_ms.observe(5000)

        # ``_count`` / ``_sum`` are the canonical histogram samples.
        samples = _collect_samples(metrics_module.research_full_brief_ms)
        sum_samples = [s for s in samples if s.name == "research_full_brief_ms_sum"]
        count_samples = [s for s in samples if s.name == "research_full_brief_ms_count"]
        assert sum_samples and count_samples
        assert sum_samples[0].value == 5000
        assert count_samples[0].value == 1

    def test_histogram_buckets_cover_latency_slos(self) -> None:
        """Req 15.9 — guardrail overhead budgeted ≤50 ms; design §13.1 —
        full-brief 15 s reference. The histograms need buckets that
        straddle those thresholds or the operator dashboard loses
        resolution at the SLO boundary.
        """
        hist = metrics_module.research_guardrail_overhead_ms
        # Observations exactly on the SLO threshold (50 ms) and under.
        hist.observe(10)
        hist.observe(50)
        hist.observe(200)

        samples = _collect_samples(hist)
        count = next(s for s in samples if s.name.endswith("_count"))
        assert count.value == 3

        # Bucket containing 50 ms must exist so the dashboard can
        # compute "p95 ≤ 50 ms" directly.
        bucket_labels = {
            s.labels.get("le") for s in samples if s.name.endswith("_bucket")
        }
        # ``le="50"`` or ``le="50.0"`` depending on the client version.
        assert any(
            lbl is not None and lbl.startswith("50") for lbl in bucket_labels
        ), f"expected an le=50 bucket, saw {bucket_labels!r}"


# --------------------------------------------------------------------------- #
# render_metrics / text format                                                #
# --------------------------------------------------------------------------- #


class TestRenderMetrics:
    def test_render_metrics_returns_prometheus_text(self) -> None:
        metrics_module.research_runs_total.labels(status="done").inc()
        data, content_type = render_metrics()

        assert isinstance(data, bytes)
        # Canonical content type exposed by prometheus-client as
        # :data:`CONTENT_TYPE_LATEST`. The concrete version string
        # varies with the client library release (``0.0.4`` on older
        # clients, ``1.0.0`` on ``prometheus-client>=0.22``); we
        # assert on the ``text/plain`` prefix and a ``version=``
        # parameter so either value passes.
        assert content_type.startswith("text/plain")
        assert "version=" in content_type

        decoded = data.decode("utf-8")
        assert "research_runs_total" in decoded
        # HELP + TYPE lines are always present for a registered counter.
        assert "# HELP research_runs_total" in decoded
        assert "# TYPE research_runs_total counter" in decoded

    def test_render_metrics_includes_every_metric(self) -> None:
        """Every top-level metric name appears in the scrape payload."""
        # Touch each metric so the registry surfaces at least one
        # sample for every family. Counters need a `.inc()`;
        # histograms need an `.observe()`.
        metrics_module.research_runs_total.labels(status="done").inc()
        metrics_module.research_guardrail_blocks_total.labels(rule_id="x").inc()
        metrics_module.research_judge_failures_total.inc()
        metrics_module.research_first_token_ms.observe(100)
        metrics_module.research_first_agent_ms.observe(250)
        metrics_module.research_full_brief_ms.observe(5000)
        metrics_module.research_guardrail_overhead_ms.observe(10)

        data, _ = render_metrics()
        text = data.decode("utf-8")
        for name in (
            "research_runs_total",
            "research_guardrail_blocks_total",
            "research_judge_failures_total",
            "research_first_token_ms",
            "research_first_agent_ms",
            "research_full_brief_ms",
            "research_guardrail_overhead_ms",
        ):
            assert name in text, f"missing metric {name!r} in scrape output"


# --------------------------------------------------------------------------- #
# /metrics endpoint                                                           #
# --------------------------------------------------------------------------- #


class TestMetricsEndpoint:
    """Exercise the ``/api/v2/research/metrics`` route via TestClient."""

    def test_metrics_endpoint(self) -> None:
        # Backend-gateway is not on sys.path when ``tests/research``
        # is invoked from the project root; insert it lazily so the
        # same test file runs identically from either dir.
        import sys
        from pathlib import Path

        gateway_root = str(Path(__file__).resolve().parents[2] / "backend-gateway")
        if gateway_root not in sys.path:
            sys.path.insert(0, gateway_root)

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.routers.research import router

        app = FastAPI()
        app.include_router(router, prefix="/api/v2/research", tags=["research"])

        # Emit a sample so the scrape is non-empty.
        metrics_module.research_runs_total.labels(status="done").inc()

        client = TestClient(app)
        resp = client.get("/api/v2/research/metrics")
        assert resp.status_code == 200
        content_type = resp.headers["content-type"]
        assert content_type.startswith("text/plain")
        assert "version=" in content_type

        text = resp.text
        assert "research_runs_total" in text
        assert 'status="done"' in text


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _collect_samples(metric: object, *, name: str | None = None) -> list[_Sample]:
    """Flatten every sample from a prometheus-client metric.

    ``prometheus_client`` exposes metrics as collector objects with a
    :meth:`collect` method yielding :class:`Metric` families; each
    family has a ``samples`` list of
    ``(name, labels, value, timestamp, exemplar)`` tuples. The helper
    unwraps that into a flat list of lightweight dataclass samples so
    assertions can read ``sample.value`` / ``sample.labels`` directly.

    When ``name`` is provided, only samples whose ``name`` matches
    (exactly) are returned — useful for counters where the sample
    name is ``<family>_total``.
    """
    out: list[_Sample] = []
    for family in metric.collect():  # type: ignore[attr-defined]
        for sample in family.samples:
            s = _Sample(name=sample.name, labels=dict(sample.labels), value=sample.value)
            if name is None or s.name == name:
                out.append(s)
    return out


class _Sample:
    """Lightweight dataclass-like wrapper for a single metric sample."""

    __slots__ = ("name", "labels", "value")

    def __init__(self, *, name: str, labels: dict[str, str], value: float) -> None:
        self.name = name
        self.labels = labels
        self.value = value

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"_Sample(name={self.name!r}, labels={self.labels!r}, value={self.value!r})"
