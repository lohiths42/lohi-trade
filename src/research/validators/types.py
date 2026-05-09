"""Shared Pydantic types for deterministic validators (design §3.7, §3.8).

``UnsupportedClaim`` is the lingua franca of the hallucination-control
pipeline: numeric validator, citation validator, refusal classifier,
and the LLM-as-Judge all emit it, and the Orchestrator's re-synthesis
loop (design §11.2, Req 16.18) consumes it. Centralising the shape in
one module keeps Task 11.1 / 11.2 / 11.3 / 12.1 aligned without any
one of them owning the contract.

Design references
-----------------
* §3.7 — Judge_LLM ``UnsupportedClaim`` schema (canonical definition).
* §3.8 — deterministic validators emit ``UnsupportedClaim`` with
  ``reason="numeric_drift"``, ``"citation_mismatch"``, etc.
* §11.2 — single re-synthesis loop feeds the list back into the
  Report_Synthesizer's context.

Satisfies
---------
* Req 14.10, Req 16.26, Req 16.27 — ``reason="numeric_drift"`` for
  numeric-fidelity violations (Task 11.1).
* Req 14.1, Req 3.11 — ``reason="citation_mismatch"`` for missing
  ``chunk_id`` (Task 11.2).
* Req 16.16 — ``reason="off_policy"`` for policy violations.
* Req 16.17 — Judge_LLM output carries a list of these (Task 12.1).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["UnsupportedClaim", "UnsupportedReason"]


# Canonical set of reasons emitted across the validator + judge stack.
# Kept as a ``Literal`` (rather than ``StrEnum``) so the resulting JSON
# Schema is a plain enum of strings — which is what the Judge prompt
# template (``prompts/v1/judge.md``, Task 10.1) asks the model to
# return.
UnsupportedReason = Literal[
    "no_citation",
    "citation_mismatch",
    "numeric_drift",
    "contradiction",
    "off_policy",
]


class UnsupportedClaim(BaseModel):
    """A single claim in a ``ResearchBrief`` that failed validation.

    The shape is exactly as specified in design §3.7 so the Judge_LLM
    can serialise its findings into the same model the deterministic
    validators emit — the Orchestrator does not need to know which
    layer flagged the claim.

    Attributes
    ----------
    section:
        Name of the ``ResearchBrief`` section the claim lives in
        (e.g. ``"financial_highlights"``, ``"management_commentary"``).
        Matches the section names in
        :class:`~src.research.validators.types` once the full
        ``ResearchBrief`` Pydantic model is introduced in Task 13.8.
    claim_text:
        Verbatim substring of the brief that carries the problem.
        For numeric drift this is the numeric token as it appears
        (e.g. ``"₹1,234.56 Cr"``); for citation mismatch this is the
        sentence whose citation does not resolve.
    start_offset:
        Inclusive character offset of ``claim_text`` inside the
        section body (``content_md``). Zero-based.
    end_offset:
        Exclusive character offset — ``content_md[start_offset:end_offset]``
        is expected to equal ``claim_text``. Validated to be strictly
        greater than ``start_offset`` so downstream slicing never
        silently produces an empty string.
    reason:
        One of :data:`UnsupportedReason`. ``"numeric_drift"`` is emitted
        by the numeric validator (Task 11.1);
        ``"citation_mismatch"`` / ``"no_citation"`` by the citation
        validator (Task 11.2); ``"contradiction"`` and
        ``"off_policy"`` by the Judge_LLM (Task 12.1).
    """

    model_config = ConfigDict(extra="forbid")

    section: str = Field(
        ...,
        min_length=1,
        description="Name of the ResearchBrief section that contains the claim.",
    )
    claim_text: str = Field(
        ...,
        min_length=1,
        description="Verbatim substring of the section that failed validation.",
    )
    start_offset: int = Field(
        ...,
        ge=0,
        description="Inclusive character offset of claim_text within the section body.",
    )
    end_offset: int = Field(
        ...,
        gt=0,
        description="Exclusive character offset of claim_text within the section body.",
    )
    reason: UnsupportedReason = Field(
        ...,
        description="Why this claim is unsupported (see UnsupportedReason).",
    )

    def model_post_init(self, __context: object) -> None:
        """Enforce ``end_offset > start_offset`` (empty spans are bugs)."""
        if self.end_offset <= self.start_offset:
            raise ValueError(
                "UnsupportedClaim.end_offset must be strictly greater than "
                f"start_offset (got start={self.start_offset}, "
                f"end={self.end_offset})"
            )
