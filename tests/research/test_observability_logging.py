"""Unit tests for Phase 18 Task 20.1 — structured logging helpers.

Exercises :mod:`src.research.agents.logging` and
:mod:`src.research.judge.logging` using pytest's ``caplog`` fixture so
the JSON log lines emitted per Sub_Agent, per retrieval call, per
Orchestrator milestone, and per Judge call can be asserted on directly.

Requirements: 13.5, 9.6
Design: §15
"""

from __future__ import annotations

import logging
from uuid import uuid4

import pytest

from src.research.agents.logging import (
    log_orchestrator_event,
    log_retrieval_call,
    log_sub_agent_invocation,
)
from src.research.judge.logging import log_judge_call

# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _records_for(caplog: pytest.LogCaptureFixture, message: str) -> list[logging.LogRecord]:
    """Return the log records whose ``message`` attribute matches ``message``.

    The :class:`~src.utils.logger.ComponentLogger` emits the event name
    as the ``message`` positional arg, so ``record.message`` (populated
    by :meth:`LogRecord.getMessage`) contains the same string. We walk
    ``caplog.records`` to avoid depending on which underlying logger
    name the helper happened to resolve.
    """
    return [r for r in caplog.records if r.getMessage() == message]


# --------------------------------------------------------------------------- #
# log_sub_agent_invocation                                                     #
# --------------------------------------------------------------------------- #


class TestLogSubAgentInvocation:
    """One structured INFO line per Sub_Agent invocation (Req 13.5)."""

    def test_log_sub_agent_invocation_emits_structured_line(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        run_id = uuid4()
        user_id = uuid4()

        with caplog.at_level(logging.INFO):
            log_sub_agent_invocation(
                run_id=run_id,
                user_id=user_id,
                agent_name="filings",
                kind="ok",
                section_name="financial_highlights",
                wall_time_ms=1234,
                input_tokens=512,
                output_tokens=256,
                reason="",
            )

        records = _records_for(caplog, "sub_agent_invocation")
        assert len(records) == 1
        rec = records[0]
        assert rec.levelno == logging.INFO
        # UUIDs are stringified so JSON consumers can ingest them
        # without a custom decoder.
        assert rec.run_id == str(run_id)
        assert rec.user_id == str(user_id)
        assert rec.agent_name == "filings"
        assert rec.kind == "ok"
        assert rec.section_name == "financial_highlights"
        assert rec.wall_time_ms == 1234
        assert rec.input_tokens == 512
        assert rec.output_tokens == 256
        assert rec.reason == ""

    def test_log_sub_agent_invocation_preserves_reason_text(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        run_id = uuid4()
        user_id = uuid4()

        with caplog.at_level(logging.INFO):
            log_sub_agent_invocation(
                run_id=run_id,
                user_id=user_id,
                agent_name="macro",
                kind="no_data",
                section_name="macro_context",
                wall_time_ms=0,
                input_tokens=0,
                output_tokens=0,
                reason="no_data: nothing indexed for RELIANCE",
            )
        records = _records_for(caplog, "sub_agent_invocation")
        assert len(records) == 1
        assert records[0].kind == "no_data"
        assert records[0].reason.startswith("no_data:")

    def test_log_sub_agent_invocation_redacts_secrets(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The helper forwards only the named fields.

        ``api_key`` / ``secret`` / ``token`` / ``password`` / ``totp`` are
        handled by the :class:`StructuredFormatter` in
        :mod:`src.utils.logger` — since :func:`log_sub_agent_invocation`
        takes an explicit keyword-argument set, there is no path for a
        sensitive field to reach the log record in the first place.
        This test documents that guarantee by asserting no known-
        sensitive attribute is attached to the record.
        """
        run_id = uuid4()
        user_id = uuid4()

        with caplog.at_level(logging.INFO):
            log_sub_agent_invocation(
                run_id=run_id,
                user_id=user_id,
                agent_name="filings",
                kind="ok",
                section_name="summary",
                wall_time_ms=42,
                input_tokens=0,
                output_tokens=0,
            )

        records = _records_for(caplog, "sub_agent_invocation")
        assert records, "expected one sub_agent_invocation record"
        record = records[0]
        for sensitive in ("api_key", "secret", "token", "password", "totp"):
            assert not hasattr(record, sensitive), (
                f"sensitive field {sensitive!r} leaked into log record"
            )


# --------------------------------------------------------------------------- #
# log_retrieval_call                                                           #
# --------------------------------------------------------------------------- #


class TestLogRetrievalCall:
    def test_log_retrieval_call_emits_structured_line(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        run_id = uuid4()
        user_id = uuid4()

        with caplog.at_level(logging.INFO):
            log_retrieval_call(
                run_id=run_id,
                user_id=user_id,
                agent_name="filings",
                k=10,
                symbol="RELIANCE",
                wall_time_ms=78,
                hit_count=8,
            )

        records = _records_for(caplog, "retrieval_call")
        assert len(records) == 1
        rec = records[0]
        assert rec.levelno == logging.INFO
        assert rec.agent_name == "filings"
        assert rec.k == 10
        assert rec.symbol == "RELIANCE"
        assert rec.wall_time_ms == 78
        assert rec.hit_count == 8
        assert rec.run_id == str(run_id)

    def test_log_retrieval_call_accepts_null_symbol(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        run_id = uuid4()
        user_id = uuid4()
        with caplog.at_level(logging.INFO):
            log_retrieval_call(
                run_id=run_id,
                user_id=user_id,
                agent_name="macro",
                k=5,
                symbol=None,
                wall_time_ms=12,
                hit_count=0,
            )
        records = _records_for(caplog, "retrieval_call")
        assert len(records) == 1
        assert records[0].symbol is None


# --------------------------------------------------------------------------- #
# log_orchestrator_event                                                       #
# --------------------------------------------------------------------------- #


class TestLogOrchestratorEvent:
    def test_log_orchestrator_event_emits_structured_line(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        run_id = uuid4()
        user_id = uuid4()

        with caplog.at_level(logging.INFO):
            log_orchestrator_event(
                run_id=run_id,
                user_id=user_id,
                event="plan_done",
                agents_requested=["filings", "fundamentals"],
            )

        records = _records_for(caplog, "plan_done")
        assert len(records) == 1
        rec = records[0]
        assert rec.event == "plan_done"
        assert rec.agents_requested == ["filings", "fundamentals"]
        assert rec.run_id == str(run_id)
        assert rec.user_id == str(user_id)

    @pytest.mark.parametrize(
        "event",
        ["plan_done", "fan_out_start", "fan_out_done", "synthesis_done", "judge_done"],
    )
    def test_log_orchestrator_event_supports_canonical_events(
        self, caplog: pytest.LogCaptureFixture, event: str,
    ) -> None:
        run_id = uuid4()
        user_id = uuid4()
        with caplog.at_level(logging.INFO):
            log_orchestrator_event(
                run_id=run_id,
                user_id=user_id,
                event=event,
            )
        records = _records_for(caplog, event)
        assert len(records) == 1
        assert records[0].event == event


# --------------------------------------------------------------------------- #
# log_judge_call                                                               #
# --------------------------------------------------------------------------- #


class TestLogJudgeCall:
    def test_log_judge_call_emits_structured_line(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        run_id = uuid4()

        with caplog.at_level(logging.INFO):
            log_judge_call(
                run_id=run_id,
                user_id=None,
                model_id="nvidia_nim/llama-3",
                elapsed_ms=1850,
                safe_to_display=True,
                min_score=0.7,
                unsupported_count=0,
                off_policy_count=0,
                retry_count=0,
            )

        records = _records_for(caplog, "judge_call")
        assert len(records) == 1
        rec = records[0]
        assert rec.levelno == logging.INFO
        assert rec.run_id == str(run_id)
        assert rec.user_id is None
        assert rec.model_id == "nvidia_nim/llama-3"
        assert rec.elapsed_ms == 1850
        assert rec.safe_to_display is True
        assert rec.min_score == pytest.approx(0.7)
        assert rec.unsupported_count == 0
        assert rec.off_policy_count == 0
        assert rec.retry_count == 0

    def test_log_judge_call_stringifies_user_id(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """``user_id`` is optional but when supplied it is stringified."""
        run_id = uuid4()
        user_id = uuid4()
        with caplog.at_level(logging.INFO):
            log_judge_call(
                run_id=run_id,
                user_id=user_id,
                model_id="ollama/llama2",
                elapsed_ms=500,
                safe_to_display=False,
                min_score=0.7,
                unsupported_count=3,
                off_policy_count=1,
                retry_count=1,
            )
        records = _records_for(caplog, "judge_call")
        assert len(records) == 1
        assert records[0].user_id == str(user_id)
        assert records[0].safe_to_display is False
        assert records[0].unsupported_count == 3
