"""Deterministic post-synthesis validators (design §3.8).

Catches hallucinations an LLM judge might miss:

- :mod:`numeric_validator` — every numeric token in the brief must
  appear within epsilon in at least one cited chunk (Req 14.10,
  Req 16.26–16.27).
- :mod:`citation_validator` — every cited ``chunk_id`` must resolve
  in the active Vector_Store for the run's ``(user_id, symbol)``
  namespace (Req 3.11, Req 14.1).
- :mod:`refusal_classifier` — flags prompts falling under the
  ``Refusal_Policy`` (buy/sell/hold, price targets, trade suggestions,
  order placement, fund transfers, code execution); Req 14.11,
  Req 16.28, design §3.8 / §10.1.

The shared :class:`~src.research.validators.types.UnsupportedClaim`
contract (design §3.7) is the common output shape across every
validator and the LLM-as-Judge (Task 12.1).
"""

from src.research.validators.citation_validator import (
    CitationValidator,
    validate_citations,
)
from src.research.validators.numeric_validator import (
    DEFAULT_EPSILON,
    NumericToken,
    NumericUnit,
    NumericValidator,
    extract_numeric_tokens,
    validate_numeric_fidelity,
)
from src.research.validators.refusal_classifier import (
    RefusalClassifier,
    RefusalReason,
    RefusalSignal,
    classify_refusal,
)
from src.research.validators.types import UnsupportedClaim, UnsupportedReason

__all__ = [
    # Shared types
    "UnsupportedClaim",
    "UnsupportedReason",
    # Numeric validator
    "DEFAULT_EPSILON",
    "NumericToken",
    "NumericUnit",
    "NumericValidator",
    "extract_numeric_tokens",
    "validate_numeric_fidelity",
    # Citation validator
    "CitationValidator",
    "validate_citations",
    # Refusal classifier
    "RefusalClassifier",
    "RefusalReason",
    "RefusalSignal",
    "classify_refusal",
]
