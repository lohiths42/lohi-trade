"""Deterministic Refusal_Policy classifier (design §3.8, §10.1, §12).

A regex + keyword classifier over the **user prompt** that returns a
:class:`RefusalSignal` when the input falls under the documented
:data:`~src.research.guardrails.refusal_policy.REFUSAL_POLICY_BLOCK`.

Scope
-----
The Refusal_Policy (Req 16.28, Req 16.29, design §10.1) lists the
categories Lohi-Research will refuse to answer on, namely:

* **buy / sell / hold** recommendations.
* **price targets** or price predictions.
* **trade suggestions** of any shape.
* **order placement** instructions.
* **fund transfers**.
* **arbitrary code execution**.

This module classifies a raw user prompt into one of those buckets via
pre-compiled regex patterns. It has two callers (design §3.8):

1. The **Guardrail input phase**
   (:class:`~src.research.guardrails.pydantic_guard.PydanticGuardrail`)
   uses the classifier alongside the YAML regex ruleset to short-circuit
   refusal before any Sub_Agent is invoked.
2. The **offline rule-based Judge** (design §11.4, Req 16.22) uses it
   as part of the regex policy check when no cloud Judge_LLM is
   available.

Why a purpose-built classifier
------------------------------
The v1 YAML ruleset
(:file:`src/research/guardrails/rules/v1.yaml`) carries a single
``RP-001 trade_advice`` rule that matches a handful of phrasings.
That rule drives the **refuse / allow** decision in the guardrail;
what it does **not** give callers is the *shape* of the refusal —
whether the prompt is asking about a price target, an order, a fund
transfer, or code execution. The rule-based Judge and the audit log
both want that shape so operators can see which policy category the
refusal landed in.

This module therefore:

* owns a richer set of per-category patterns (fund-transfer and
  code-execution patterns do not appear in the YAML ruleset, which is
  deliberately minimal per design §10.3), and
* returns a **typed reason** (``RefusalReason``) rather than a bool,
  so the Guardrail + Judge can record the refusal category in the
  :class:`~src.research.guardrails.refusal_policy.RefusalResult` and
  downstream audit log.

Relationship to the YAML ruleset
--------------------------------
The classifier's ``RP-001`` patterns are a **superset** of the YAML
``RP-001`` patterns. The YAML rule remains the source of truth for
the Guardrail's refuse/allow decision; this classifier is additive —
when the YAML rule fires, the classifier will fire too with a more
specific ``RefusalReason``, and when the classifier fires without
the YAML rule (rare, happens only for fund-transfer / code-execution
prompts the YAML ruleset does not cover) the Guardrail treats that
as an additional reason to refuse.

Satisfies
---------
* Req 14.11 — refusal property: for prompts matching the
  ``Refusal_Policy`` the system returns a refusal with an
  explanation and does not produce a recommendation.
* Req 16.28 — refuse buy/sell/hold, price targets, trade suggestions.
* Req 16.29 — centralised Refusal_Policy shape surfaced via
  :class:`RefusalSignal`.

Design references
-----------------
* §3.8 — deterministic ``refusal_classifier.py`` validator shipped
  alongside numeric + citation validators.
* §10.1 — default framework-light refusal policy.
* §11.4 / §12 — offline rule-based Judge performs a refusal-policy
  regex check using this classifier.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import ClassVar, Final, Literal

__all__ = [
    "RefusalClassifier",
    "RefusalReason",
    "RefusalSignal",
    "classify_refusal",
]


# --------------------------------------------------------------------------- #
# Public types                                                                #
# --------------------------------------------------------------------------- #


# Canonical set of refusal reasons. Kept as a ``Literal`` (matching
# ``UnsupportedReason`` in :mod:`src.research.validators.types`) so
# downstream JSON serialisation is a plain enum of strings, and so
# the Pydantic models in the Guardrail layer can validate the value
# without importing a ``StrEnum``.
#
# The set mirrors design §10.1 / Req 16.29 one-for-one. Callers that
# want a human label may use :func:`refusal_reason_label`.
RefusalReason = Literal[
    "buy_sell_hold",
    "price_target",
    "trade_suggestion",
    "order_placement",
    "code_execution",
    "fund_transfer",
]


@dataclass(frozen=True)
class RefusalSignal:
    """Result of classifying one user prompt against the Refusal_Policy.

    Attributes
    ----------
    matched:
        ``True`` when at least one policy pattern fired. The
        remaining fields are meaningful only when ``matched`` is
        ``True``; on a no-match the classifier returns
        :data:`RefusalSignal.NO_MATCH` whose other fields are ``None``.
    reason:
        Which policy category fired. When the prompt matches more
        than one category, the **first** match in the evaluation
        order (spelled out in :data:`_REASON_ORDER`) wins. The order
        is chosen so more-specific categories (``order_placement``,
        ``fund_transfer``, ``code_execution``) preempt the broader
        ``trade_suggestion`` bucket.
    matched_rule_id:
        Stable identifier of the rule that fired, matching the
        ``rule_id`` convention used by
        :class:`~src.research.guardrails.pydantic_guard.GuardrailDecision`
        and :class:`~src.research.guardrails.refusal_policy.RefusalResult`.
        Every category has its own id under the ``RP-`` namespace
        (e.g. ``"RP-001"`` for buy/sell/hold, ``"RP-006"`` for fund
        transfers) so operators can trace the refusal back to the
        exact pattern that fired.
    matched_text:
        Verbatim substring of the prompt that tripped the pattern.
        Preserved so audit logs and the re-synthesis loop can show
        exactly which words triggered the classification. Bounded to
        :data:`_MAX_MATCHED_TEXT_LEN` characters to keep log records
        small.

    """

    matched: bool
    reason: RefusalReason | None
    matched_rule_id: str | None
    matched_text: str | None

    #: Sentinel returned by the classifier when no pattern matched.
    #: Using a single frozen instance means callers can compare with
    #: ``result is RefusalSignal.NO_MATCH`` — useful in hot paths.
    #: Declared as :class:`ClassVar` so the dataclass machinery does
    #: not treat it as a field; the actual value is assigned below
    #: once the class object exists.
    NO_MATCH: ClassVar[RefusalSignal]


# Frozen sentinel for the no-match case. Assigned after the class
# definition because a frozen dataclass cannot reference itself in a
# class-body default.
RefusalSignal.NO_MATCH = RefusalSignal(
    matched=False,
    reason=None,
    matched_rule_id=None,
    matched_text=None,
)


# --------------------------------------------------------------------------- #
# Rule identifiers                                                            #
# --------------------------------------------------------------------------- #


# Rule ids in the ``RP-`` (Refusal_Policy) namespace. ``RP-001`` is
# kept aligned with the ``RP-001`` row in ``v1.yaml`` so the two
# sources agree on the canonical id for trade advice; the remaining
# ids are new and owned exclusively by this module.
_RULE_ID_BUY_SELL_HOLD: Final[str] = "RP-001"
_RULE_ID_PRICE_TARGET: Final[str] = "RP-002"
_RULE_ID_TRADE_SUGGESTION: Final[str] = "RP-003"
_RULE_ID_ORDER_PLACEMENT: Final[str] = "RP-004"
_RULE_ID_CODE_EXECUTION: Final[str] = "RP-005"
_RULE_ID_FUND_TRANSFER: Final[str] = "RP-006"


# --------------------------------------------------------------------------- #
# Pattern tables                                                              #
# --------------------------------------------------------------------------- #
#
# Notes on the regex style:
#
# * Every pattern is case-insensitive via the ``(?i)`` leading flag
#   group so callers compiling with ``re.IGNORECASE`` is unnecessary
#   — this matches the style used by ``v1.yaml``.
# * Word boundaries (``\b``) are used around short verbs like
#   ``buy`` / ``sell`` to avoid matching inside longer words such as
#   ``"buyer"`` or ``"selloff"`` in a neutral sense. The trade-advice
#   patterns specifically anchor on interrogative / imperative shapes
#   (``"should I buy"``, ``"buy recommendation"``) because a bare
#   ``"buy"`` verb appears in neutral sentences too (``"the company
#   will buy back shares"``) and a blanket match would over-refuse.
# * Patterns use ``\s+`` between multi-word tokens so extra
#   whitespace is tolerated — matches the ``(?i)…\s+…`` convention in
#   ``v1.yaml`` and keeps the classifier robust against the
#   ``extra_whitespace`` mutation class exercised by the guardrail
#   bypass property test.

# Order-placement: broker-action verbs. Checked before the broader
# trade-suggestion bucket so a prompt like "place a buy order for
# RELIANCE" is classified as ``order_placement`` (the more specific
# shape) rather than falling back to ``trade_suggestion``.
_PATTERNS_ORDER_PLACEMENT: Final[tuple[str, ...]] = (
    r"(?i)\bplace\s+(an?\s+)?(buy|sell|market|limit|stop)\s*order\b",
    r"(?i)\bplace\s+(an?\s+)?order\b",
    r"(?i)\b(submit|send|execute|route)\s+(an?\s+|the\s+|my\s+)?order\b",
    r"(?i)\border\s+(placement|execution|entry)\b",
    r"(?i)\b(buy|sell|purchase)\s+\d+\s+(shares?|units?|lots?)\b",
)

# Fund transfers. Covers both the retail framing ("transfer funds",
# "send money") and the programmatic framing ("wire transfer",
# "initiate transfer"). Does not match generic "transfer" (which
# legitimately appears in filings discussing "stock transfer" or
# "share transfer").
_PATTERNS_FUND_TRANSFER: Final[tuple[str, ...]] = (
    r"(?i)\btransfer\s+(my\s+|the\s+)?(funds?|money|balance|cash|\$|₹|rs\.?)\b",
    r"(?i)\b(send|wire|remit|deposit|withdraw)\s+(money|funds?|cash|\$|₹|rs\.?)\b",
    r"(?i)\b(initiate|make|process)\s+(a\s+)?(wire|fund|bank)\s+transfer\b",
    r"(?i)\b(fund|bank|wire)\s+transfer\b",
    r"(?i)\bmove\s+(funds?|money)\s+(to|from|into|out\s+of)\b",
)

# Code execution. Deliberately anchored on verbs that imply the
# assistant should *run* or *execute* code — reading / explaining /
# writing code is not refused, only execution.
_PATTERNS_CODE_EXECUTION: Final[tuple[str, ...]] = (
    r"(?i)\b(run|execute|eval(uate)?)\s+(this|the|that|my|some|a|the\s+following|following)?\s*(python|javascript|bash|shell|sql|code|script|command)\b",
    r"(?i)\b(run|execute)\s+this\b",
    r"(?i)\bexec(ute)?\(",
    r"(?i)\beval\(",
    r"(?i)\bos\.system\(",
    r"(?i)\bsubprocess\.(run|call|Popen)\(",
    r"(?i)\b(run|execute|launch)\s+(a\s+|the\s+)?(shell|bash|terminal)\s+command\b",
)

# Price targets. Phrasings cover both "what is the price target" and
# "predict the price" shapes.
_PATTERNS_PRICE_TARGET: Final[tuple[str, ...]] = (
    r"(?i)\bprice\s+target\b",
    r"(?i)\btarget\s+price\b",
    r"(?i)\b(predict|forecast|project)\s+(the\s+)?(price|share\s+price|stock\s+price)\b",
    r"(?i)\bwhat\s+(will|would)\s+(the\s+)?(price|share\s+price|stock\s+price)\s+be\b",
    r"(?i)\bwhere\s+(will|would)\s+(the\s+)?(price|share\s+price|stock\s+price)\s+(go|be|head)\b",
    r"(?i)\b(upside|downside)\s+target\b",
    r"(?i)\b12[- ]?month\s+(price\s+)?target\b",
)

# Buy / sell / hold. Aligned with the ``RP-001`` row in ``v1.yaml``
# plus additional phrasings ("is it a buy", "recommend buying", etc.).
# Anchored on shapes that imply a recommendation to avoid over-matching
# neutral uses of the verb.
_PATTERNS_BUY_SELL_HOLD: Final[tuple[str, ...]] = (
    r"(?i)\bshould\s+(i|we|one)\s+(buy|sell|hold)\b",
    r"(?i)\b(buy|sell|hold)\s+recommendation\b",
    r"(?i)\brecommend(ation)?\s+(to\s+)?(buy|sell|hold|buying|selling|holding)\b",
    r"(?i)\bis\s+(it|this|that|\w+)\s+(a|an)\s+(buy|sell|hold)\b",
    r"(?i)\bwould\s+you\s+(buy|sell|hold)\b",
    r"(?i)\b(buy|sell)\s+(or|vs\.?)\s+(sell|buy|hold)\b",
    r"(?i)\brating:\s*(buy|sell|hold|strong\s+buy|strong\s+sell)\b",
)

# Trade suggestions. Broader fallback bucket for prompts that imply a
# trade action without fitting one of the more specific shapes above.
# Order matters: matched after order_placement so the more specific
# bucket wins when both patterns apply.
_PATTERNS_TRADE_SUGGESTION: Final[tuple[str, ...]] = (
    r"(?i)\btrade\s+(suggestion|idea|setup|recommendation)\b",
    r"(?i)\bsuggest\s+(a\s+)?trade\b",
    r"(?i)\bwhat\s+(should|would|do)\s+(i|you)\s+trade\b",
    r"(?i)\bentry\s+(and\s+)?exit\s+(points?|levels?)\b",
    r"(?i)\b(stop[- ]?loss|take[- ]?profit|target\s+level)\b.*\b(for|on)\b",
    r"(?i)\bactionable\s+trade\b",
)


# --------------------------------------------------------------------------- #
# Compiled rule table                                                         #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _CompiledRule:
    """Internal compiled form of one refusal rule.

    Holds pre-parsed :class:`re.Pattern` objects so the hot path in
    :meth:`RefusalClassifier.classify` is a plain iteration with no
    per-call regex compilation.
    """

    rule_id: str
    reason: RefusalReason
    patterns: tuple[re.Pattern[str], ...]


def _compile_rules() -> tuple[_CompiledRule, ...]:
    """Build the ordered rule table. Evaluation order is first-match-wins.

    The order reflects specificity — more-specific categories are
    checked before the broader ``trade_suggestion`` fallback. See
    module docstring for why the ordering matters.
    """
    # Keep the declaration style compact; the ordering itself is the
    # documented contract (duplicated in :data:`_REASON_ORDER` below).
    rows: tuple[tuple[str, RefusalReason, tuple[str, ...]], ...] = (
        (_RULE_ID_ORDER_PLACEMENT, "order_placement", _PATTERNS_ORDER_PLACEMENT),
        (_RULE_ID_FUND_TRANSFER, "fund_transfer", _PATTERNS_FUND_TRANSFER),
        (_RULE_ID_CODE_EXECUTION, "code_execution", _PATTERNS_CODE_EXECUTION),
        (_RULE_ID_PRICE_TARGET, "price_target", _PATTERNS_PRICE_TARGET),
        (_RULE_ID_BUY_SELL_HOLD, "buy_sell_hold", _PATTERNS_BUY_SELL_HOLD),
        (_RULE_ID_TRADE_SUGGESTION, "trade_suggestion", _PATTERNS_TRADE_SUGGESTION),
    )
    compiled: list[_CompiledRule] = []
    for rule_id, reason, patterns in rows:
        compiled.append(
            _CompiledRule(
                rule_id=rule_id,
                reason=reason,
                patterns=tuple(re.compile(p) for p in patterns),
            ),
        )
    return tuple(compiled)


# Module-level compiled table — regex compilation happens exactly
# once at import time, not per-call.
_RULES: Final[tuple[_CompiledRule, ...]] = _compile_rules()

# Public view of the evaluation order (reasons only) — handy for
# tests and for callers that want to pre-sort their own category
# lists to match the classifier's precedence.
_REASON_ORDER: Final[tuple[RefusalReason, ...]] = tuple(r.reason for r in _RULES)


# Upper bound on ``matched_text`` length. Long matches are truncated
# with a trailing ellipsis so audit-log records stay compact while
# still carrying enough context to see why the pattern fired.
_MAX_MATCHED_TEXT_LEN: Final[int] = 120


def _truncate(text: str) -> str:
    """Clamp ``text`` to :data:`_MAX_MATCHED_TEXT_LEN` characters.

    Long prompts occasionally produce long matches (multi-line
    patterns with ``.*`` in the middle can span the whole sentence).
    Storing the full text bloats the audit log without adding useful
    signal — the first 120 characters is enough to see why the rule
    fired.
    """
    if len(text) <= _MAX_MATCHED_TEXT_LEN:
        return text
    return text[: _MAX_MATCHED_TEXT_LEN - 1].rstrip() + "…"


# --------------------------------------------------------------------------- #
# Classifier                                                                  #
# --------------------------------------------------------------------------- #


class RefusalClassifier:
    """Stateless Refusal_Policy classifier (design §3.8, Req 14.11, 16.28).

    The class is stateless — a single module-level instance
    (:data:`_DEFAULT_CLASSIFIER`) is shared by :func:`classify_refusal`.
    Constructing additional instances is cheap: the compiled rule
    table is shared at module level and nothing is re-compiled in
    ``__init__``.

    Instances are safe to share across concurrent runs and across
    threads — :class:`re.Pattern` objects are thread-safe, and the
    classifier holds no mutable state.
    """

    def classify(self, prompt: str) -> RefusalSignal:
        """Classify ``prompt`` against the Refusal_Policy.

        Parameters
        ----------
        prompt:
            Raw user prompt. May be empty; ``None``-like values are
            not accepted (callers should pass ``""`` explicitly to
            signal "no prompt available").

        Returns
        -------
        RefusalSignal
            * :data:`RefusalSignal.NO_MATCH` when no pattern fires.
            * A populated :class:`RefusalSignal` on the **first**
              rule hit in evaluation order (see module docstring for
              the rationale behind the ordering).

        Behavioural notes
        -----------------
        * Only the **first** pattern in the first matching rule is
          reported. Multi-category prompts (e.g. "should I buy and
          transfer funds") still return a single signal — the shape
          of :class:`RefusalSignal` is scalar by design so the
          Guardrail and Judge can log one reason per refusal.
        * Empty prompts return :data:`RefusalSignal.NO_MATCH`. They
          cannot trip a policy pattern and silently returning a
          no-match keeps the classifier's contract simple for
          upstream callers.

        """
        if not prompt:
            return RefusalSignal.NO_MATCH

        for rule in _RULES:
            for pattern in rule.patterns:
                match = pattern.search(prompt)
                if match is None:
                    continue
                return RefusalSignal(
                    matched=True,
                    reason=rule.reason,
                    matched_rule_id=rule.rule_id,
                    matched_text=_truncate(match.group(0)),
                )
        return RefusalSignal.NO_MATCH


# Module-level singleton used by :func:`classify_refusal`. Private so
# callers that want an instance use the class directly (keeps the
# public surface minimal).
_DEFAULT_CLASSIFIER: Final[RefusalClassifier] = RefusalClassifier()


def classify_refusal(prompt: str) -> RefusalSignal:
    """Module-level convenience wrapper around :class:`RefusalClassifier`.

    Intended for call sites that do not need to carry a classifier
    instance — chiefly the Guardrail input phase
    (:class:`~src.research.guardrails.pydantic_guard.PydanticGuardrail`)
    and the offline rule-based Judge (design §11.4, Req 16.22).

    Equivalent to::

        RefusalClassifier().classify(prompt)

    but reuses the module-level singleton so repeated calls incur no
    allocation overhead.
    """
    return _DEFAULT_CLASSIFIER.classify(prompt)
