"""Shared Refusal_Policy constants and helpers.

Every Sub_Agent, the Orchestrator, and the gateway import
:data:`REFUSAL_POLICY_BLOCK` and :func:`refuse` from this module so the
user-visible refusal wording is uniform across the system (Req 16.29,
design §10.1). Centralising the text also means updates to the policy
land in exactly one place.

The policy enumerates the actions Lohi-Research refuses to perform,
grouped to match design §10.1:

* No buy/sell/hold recommendations.
* No price targets.
* No trade suggestions or order-placement instructions.
* No fund transfers.
* No arbitrary code execution.
* Every answer is grounded in retrieved source documents with inline
  citations.

Satisfies:
    - Req 16.29 — ``Refusal_Policy`` documented and user-visible.
    - Req 14.11 — refusals carry a machine-readable reason/rule_id
      pair that the refusal classifier + property tests can inspect.

Design references:
    - §10.1 (Default framework-light refusal policy)
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["REFUSAL_POLICY_BLOCK", "RefusalResult", "refuse"]


# User-visible summary of the policy. This text is surfaced verbatim
# through the prompt skeleton's ``<refusal_policy>`` section and
# through the Research_Dashboard ``RefusalBanner`` component, so
# changes here propagate to both the model and the user without any
# additional plumbing (Req 16.29, design §3.13).
REFUSAL_POLICY_BLOCK: str = (
    "Lohi-Research is a research assistant. It does not provide buy/sell/hold "
    "recommendations, price targets, trade suggestions, order placement, fund "
    "transfers, or code execution.\n"
    "All answers are grounded in retrieved source documents with inline citations."
)


class RefusalResult(BaseModel):
    """Structured refusal surfaced to callers and logged to audit.

    The fields are deliberately small so the shape is stable across
    the Guardrail_Layer, the refusal classifier, and the gateway's
    API response (design §3.8, §3.13).

    Attributes
    ----------
    reason:
        Short machine-readable reason. Conventionally snake_case
        (e.g. ``"trade_advice"``, ``"jailbreak_attempt"``). Used for
        metrics and dashboard filtering; not user-facing.
    rule_id:
        Identifier of the rule that fired, matching the ``id`` column
        of ``src/research/guardrails/rules/v1.yaml`` (e.g. ``"RP-001"``).
        Lets operators trace the refusal back to the exact ruleset row.
    user_message:
        User-visible refusal text. Defaults to
        :data:`REFUSAL_POLICY_BLOCK` so the dashboard always shows the
        same canonical wording when a specific message is not
        supplied.
    """

    reason: str = Field(..., description="Machine-readable refusal reason (snake_case).")
    rule_id: str = Field(..., description="Rule identifier from the active guardrail ruleset.")
    user_message: str = Field(
        default=REFUSAL_POLICY_BLOCK,
        description="User-visible refusal text; defaults to the shared policy block.",
    )

    model_config = ConfigDict(extra="forbid")


def refuse(
    reason: str,
    rule_id: str,
    user_message: str | None = None,
) -> RefusalResult:
    """Construct a canonical :class:`RefusalResult`.

    Parameters
    ----------
    reason:
        Machine-readable reason. Non-empty; snake_case recommended.
    rule_id:
        Identifier of the rule that fired. Non-empty.
    user_message:
        Optional override for the user-visible text. When ``None``
        (the default), :data:`REFUSAL_POLICY_BLOCK` is used — which is
        what Sub_Agents and the gateway should prefer unless they
        have a strictly narrower message to surface.

    Returns
    -------
    RefusalResult
        A validated Pydantic model ready for logging, for inclusion in
        the ``ResearchBrief.provenance`` guardrail summary, and for
        direct serialisation to the gateway response payload.
    """
    return RefusalResult(
        reason=reason,
        rule_id=rule_id,
        user_message=user_message if user_message is not None else REFUSAL_POLICY_BLOCK,
    )
