"""Structured-logging helper for Judge_LLM invocations.

Emits one JSON line per Judge call so operators can inspect
:class:`~src.research.judge.judge.JudgeReport` fields without pulling
rows out of ``research_judge_reports``. Mirrors the Sub_Agent and
retrieval helpers in :mod:`src.research.agents.logging` so the
aggregated log stream has a uniform shape across the four stages of
a ``Research_Run``.

The project-standard structured logger
(:func:`src.utils.logger.get_logger`) already has a redaction pass
covering ``api_key|secret|token|password|totp`` (Req 9.6), so this
helper forwards every field via ``extra=`` without a further redact
step.

Satisfies
---------
* Req 13.5 — structured log line per Judge call.
* Req 9.6  — sensitive fields flow through the formatter's redaction.

Design references
-----------------
* §15 — operator dashboards backed by the same JSON log stream.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

# Match the import-path fallback used by
# :mod:`src.research.judge.async_fallback` and
# :mod:`src.research.guardrails.logging` so observability wiring stays
# uniform under trimmed test installs.
try:  # pragma: no cover - import-path fallback
    from src.utils.logger import get_logger

    _logger: Any = get_logger("ResearchJudge")
except Exception:  # noqa: BLE001 - best-effort logger wiring
    import logging

    _logger = logging.getLogger("research.judge.logging")


__all__ = ["log_judge_call"]


def log_judge_call(
    *,
    run_id: UUID,
    user_id: UUID | None,
    model_id: str,
    elapsed_ms: int,
    safe_to_display: bool,
    min_score: float,
    unsupported_count: int,
    off_policy_count: int,
    retry_count: int,
) -> None:
    """Emit one structured INFO line for a Judge_LLM call.

    Parameters
    ----------
    run_id:
        Research_Run this judgement belongs to.
    user_id:
        Optional tenant id. Intentionally nullable because
        :func:`src.research.judge.judge.invoke` does not receive a
        ``user_id`` — the call is scoped at the Orchestrator level
        and the Judge itself treats the brief as opaque text. When
        supplied, the value is stringified for JSON friendliness;
        when ``None``, the field is emitted as ``None`` so the log
        aggregator sees a stable shape.
    model_id:
        ``provider/model`` identifier for the Judge's LLM (matches
        :attr:`JudgeReport.model_id`).
    elapsed_ms:
        Wall time of the Judge call in milliseconds.
    safe_to_display:
        Outcome flag — ``True`` means the brief is safe to surface,
        ``False`` triggers the re-synthesis loop or a quality-low
        degrade (design §11.2).
    min_score:
        Operator-configured minimum groundedness score
        (``research.judge.min_score``). Logged so operators can see
        the cut-off that was in effect at decision time.
    unsupported_count:
        Number of :class:`UnsupportedClaim` entries in the report.
    off_policy_count:
        Number of off-policy findings (Req 16.16).
    retry_count:
        Re-synthesis pass counter (0 on the first invocation; 1 on
        the re-synthesis pass). Design §11.2 caps this at 1.
    """
    fields = {
        "run_id": str(run_id),
        "user_id": str(user_id) if user_id is not None else None,
        "model_id": model_id,
        "elapsed_ms": int(elapsed_ms),
        "safe_to_display": bool(safe_to_display),
        "min_score": float(min_score),
        "unsupported_count": int(unsupported_count),
        "off_policy_count": int(off_policy_count),
        "retry_count": int(retry_count),
    }
    _emit("judge_call", fields)


# --------------------------------------------------------------------------- #
# Internal helpers                                                            #
# --------------------------------------------------------------------------- #


def _emit(message: str, fields: dict[str, Any]) -> None:
    """Emit ``fields`` as the ``extra`` payload of an INFO log line.

    Mirrors the helper in :mod:`src.research.agents.logging` —
    duplicated rather than imported to keep this module free of a
    cross-package dependency inside ``src/research/``.
    """
    try:
        _logger.info(message, extra=fields)
    except TypeError:  # pragma: no cover - very old logger variants
        _logger.info("%s %s", message, fields)
