"""Deterministic numeric-fidelity validator (design §3.8, §12).

Catches hallucinated numbers that an LLM judge might miss.

Flow
----
1. Extract every **numeric token** from each section of a
   ``ResearchBrief`` using a locale-aware tokenizer that understands
   Indian-market conventions.
2. For each token, compute a canonical ``(value, unit, original_text)``
   form.
3. Check whether an equivalent token (within ``epsilon`` relative
   tolerance) appears in **at least one** of the brief's cited chunks.
4. Every token that fails the check becomes an
   :class:`~src.research.validators.types.UnsupportedClaim` with
   ``reason="numeric_drift"`` (design §3.7, §3.8, Req 16.26–16.27).

Token grammar
-------------
Supported shapes (the order matters — longer matches are tried first):

=============================  ============================================
Example                        Canonical form
=============================  ============================================
``₹1,234.56`` / ``Rs. 1,234.56``  ``(1234.56, "INR", original)``
``$1,234.56``                  ``(1234.56, "USD", original)``
``1.2 Cr`` / ``1.2 crore``     ``(12_000_000.0, "count_or_inr", original)``
``2.5 lakh`` / ``2.5 L``       ``(250_000.0, "count_or_inr", original)``
``2.5%`` / ``2.5 percent``     ``(2.5, "percent", original)``
``FY24`` / ``FY2024``          ``(2024.0, "fiscal_year", original)``
``Q1 FY25`` / ``Q1FY25``       ``(20251.0, "fiscal_quarter", original)``
``2023-24``                    ``(2024.0, "fiscal_year", original)``
``1,234.56`` (bare)            ``(1234.56, "number", original)``
=============================  ============================================

Why a purpose-built parser and not ``locale``
---------------------------------------------
Python's ``locale`` module cannot parse ``"1.2 Cr"`` or ``"Q1 FY25"``,
and setting the process locale has global side-effects that would
leak into concurrent Sub_Agent runs. The patterns here are small,
explicit, and deterministic — which matches the other deterministic
validators in design §3.8.

Why a **relative** epsilon (not absolute)
-----------------------------------------
The same claim can appear in a brief as ``"₹1,234.56 Cr"`` and in a
cited chunk as ``"12,345.6 million"``. A fixed absolute epsilon (say
``1.0``) would be loose for tiny growth percentages (``2.5%`` vs
``2.51%`` is ``0.01`` apart) and tight for large rupee figures
(``₹12,345 Cr`` vs ``₹12,346 Cr``). A **relative** epsilon (default
``0.01`` = 1%) scales naturally across both. Callers can override via
the constructor to enforce a stricter or looser bound per deployment.

Fiscal-year / fiscal-quarter shapes
-----------------------------------
``FY24`` normalises to the ending calendar year ``2024`` (the Indian
fiscal year FY24 runs 1 Apr 2023 – 31 Mar 2024). ``Q1 FY25`` expands
to ``20251`` — a synthetic scalar built as
``fiscal_year * 10 + quarter`` — purely so an exact-match comparison
works cleanly against chunks that use the same shape. Textual-form
variants (``FY24`` vs ``FY 24`` vs ``FY2024``) all collapse to the
same scalar, so cosmetic differences don't trigger false positives.

Inputs accepted
---------------
The full ``ResearchBrief`` Pydantic model lands in Task 13.8. Until
then, :func:`validate_numeric_fidelity` also accepts a plain
``dict[str, str]`` mapping ``section_name -> content_md`` so the
numeric validator is usable today by every caller that already has
section text in hand. When the full model exists the same function
accepts it verbatim via duck-typing.

Satisfies
---------
* Req 14.10, Req 16.26 — numeric fidelity property; every numeric
  value in a brief appears within epsilon in at least one cited chunk.
* Req 16.27 — violations trigger re-synthesis via
  :class:`UnsupportedClaim` with ``reason="numeric_drift"``.

Design references
-----------------
* §3.8 (Validators shipped — ``numeric_validator.py``).
* §12 (Hallucination defences — deterministic numeric-extraction
  validator over every Research_Brief).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final, Iterable, Literal, Mapping, Protocol, runtime_checkable

from src.research.validators.types import UnsupportedClaim

__all__ = [
    "NumericUnit",
    "NumericToken",
    "NumericValidator",
    "validate_numeric_fidelity",
]


# --------------------------------------------------------------------------- #
# Constants                                                                   #
# --------------------------------------------------------------------------- #

# Default relative epsilon: 1% — loose enough to accept rounding
# differences between ``1,234.56`` and ``1,234.6`` but tight enough
# to catch a crore-scale hallucination. Overridable per caller via
# :class:`NumericValidator` constructor, and configurable via
# ``research.retrieval.numeric_validator.epsilon`` once the config
# loader wires it up.
DEFAULT_EPSILON: Final[float] = 0.01

# Normalised canonical units for the parsed scalar value. We keep
# ``count_or_inr`` for lakh/crore because those suffixes are used
# interchangeably for rupee amounts and plain counts in Indian
# filings — any claim drift is about the **magnitude**, not the unit
# interpretation, so we compare against chunks that have the same
# shape regardless of whether the quantity is rupees or units.
NumericUnit = Literal[
    "INR",
    "USD",
    "percent",
    "count_or_inr",  # lakh / crore suffixes
    "fiscal_year",
    "fiscal_quarter",
    "number",        # bare decimals / integers
]


# Multipliers for the lakh / crore suffixes.
_LAKH_MULT: Final[Decimal] = Decimal("100000")     # 1 lakh = 1e5
_CRORE_MULT: Final[Decimal] = Decimal("10000000")  # 1 crore = 1e7

# Two-digit fiscal-year window. ``FY24`` → ``2024``, ``FY99`` → ``1999``.
# Pivot is 50: ``FY49`` → ``2049``, ``FY50`` → ``1950``. Matches
# industry convention for BSE/NSE filings dated back to 1999-2000.
_FY_PIVOT: Final[int] = 50
_FY_CENTURY_RECENT: Final[int] = 2000
_FY_CENTURY_LEGACY: Final[int] = 1900


# --------------------------------------------------------------------------- #
# Public dataclass                                                            #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class NumericToken:
    """One numeric token extracted from text.

    Attributes
    ----------
    value:
        Canonical decimal magnitude. For percentages this is the
        percent value itself (``2.5`` for ``"2.5%"``); for lakh/crore
        this is the expanded integer (``12_000_000`` for ``"1.2 Cr"``);
        for fiscal years this is the ending calendar year; for fiscal
        quarters this is ``fiscal_year * 10 + quarter`` (synthetic
        scalar used only for equality comparison, see module docstring).
    unit:
        One of :data:`NumericUnit`. Determines which epsilon applies
        and which other tokens are comparable.
    original_text:
        The exact substring that produced this token, preserved
        verbatim so :class:`UnsupportedClaim.claim_text` reflects
        what the reader will see in the brief.
    start_offset:
        Inclusive character offset of ``original_text`` in the source
        string (section body).
    end_offset:
        Exclusive character offset — ``text[start:end] == original_text``.
    """

    value: Decimal
    unit: NumericUnit
    original_text: str
    start_offset: int
    end_offset: int


# --------------------------------------------------------------------------- #
# Patterns                                                                    #
# --------------------------------------------------------------------------- #
#
# Order matters. Longer / more-specific shapes are listed first so the
# regex alternation prefers ``Q1 FY25`` over the naked ``Q1`` followed
# by a separate ``FY25`` match; and ``₹1,234.56 Cr`` over a naked
# ``₹1,234.56`` followed by a separate ``Cr``.

# Shared numeric body: ``1,234.56`` / ``1234.56`` / ``1,234`` / ``1234``.
# Order inside the alternation matters: the grouped-with-commas
# alternative is tried first so ``1,234.56`` matches as a single token
# rather than ``1`` + ``,234.56``. The plain-digits alternative then
# catches bare runs like ``12000000`` that have no grouping at all.
# Both alternatives admit an optional ``[+-]`` sign and optional
# fractional tail, so every decimal shape in the corpus is covered.
_NUMBER_BODY = r"[+-]?\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|[+-]?\d+(?:\.\d+)?"

# Indian-rupee and US-dollar symbols, with or without ``Rs.`` prefix.
_INR_PREFIX = r"(?:₹|Rs\.?|INR\s)"
_USD_PREFIX = r"(?:\$|USD\s)"

# Multiplier suffixes. ``L`` and ``lakh`` / ``lakhs``; ``Cr`` /
# ``crore`` / ``crores``. Case-insensitive match applied at compile time.
_LAKH_SUFFIX = r"(?:lakhs?|L)"
_CRORE_SUFFIX = r"(?:crores?|Cr)"

# Percent: ``2.5%``, ``2.5 %``, ``2.5 percent``, ``2.5 pct``.
_PERCENT_SUFFIX = r"(?:%|\s?percent|\s?pct)"

# Quarter + fiscal year: ``Q1 FY25``, ``Q1FY25``, ``Q1 FY2025``.
_FY_TAIL = r"FY\s?\d{2}(?:\d{2})?"
_FQ_PATTERN = rf"Q[1-4]\s?{_FY_TAIL}"

# Fiscal year alone: ``FY24`` / ``FY2024`` / ``FY 24``.
_FY_PATTERN = _FY_TAIL

# Indian fiscal-year range: ``2023-24`` / ``FY2023-24``. The 2-digit
# tail must immediately follow the 4-digit head (no space).
_FY_RANGE_PATTERN = r"(?:FY\s?)?\d{4}-\d{2}\b"

# Currency with optional multiplier suffix.
_INR_MULT_PATTERN = rf"{_INR_PREFIX}\s?(?:{_NUMBER_BODY})(?:\s?(?:{_LAKH_SUFFIX}|{_CRORE_SUFFIX}))?"
_USD_MULT_PATTERN = rf"{_USD_PREFIX}\s?(?:{_NUMBER_BODY})(?:\s?(?:{_LAKH_SUFFIX}|{_CRORE_SUFFIX}))?"

# Lakh / crore without currency prefix: ``1.2 Cr``, ``2.5 lakh``.
_MULT_ONLY_PATTERN = rf"(?:{_NUMBER_BODY})\s?(?:{_LAKH_SUFFIX}|{_CRORE_SUFFIX})"

# Percent.
_PERCENT_PATTERN = rf"(?:{_NUMBER_BODY}){_PERCENT_SUFFIX}"

# Bare decimal / integer — last-resort fallback. Deliberately
# restrictive: at least one digit and optional grouping/decimal. We
# require a word boundary or whitespace on either side so we don't
# over-match bits of longer tokens that an earlier pattern already
# owns.
_BARE_NUMBER_PATTERN = rf"(?<![A-Za-z0-9]){_NUMBER_BODY}(?![A-Za-z%0-9])"

# Compiled master pattern — alternation in priority order. The
# named groups let the parse step dispatch without re-matching.
_MASTER_PATTERN = re.compile(
    "|".join(
        f"(?P<{name}>{pattern})"
        for name, pattern in (
            ("fiscal_quarter", _FQ_PATTERN),
            ("fiscal_range",   _FY_RANGE_PATTERN),
            ("fiscal_year",    _FY_PATTERN),
            ("inr",            _INR_MULT_PATTERN),
            ("usd",            _USD_MULT_PATTERN),
            ("mult_only",      _MULT_ONLY_PATTERN),
            ("percent",        _PERCENT_PATTERN),
            ("bare",           _BARE_NUMBER_PATTERN),
        )
    ),
    re.IGNORECASE,
)


# --------------------------------------------------------------------------- #
# Token extraction                                                            #
# --------------------------------------------------------------------------- #


def _strip_grouping(number_text: str) -> Decimal:
    """Parse a number body like ``"1,234.56"`` into :class:`Decimal`.

    Handles Indian grouping (``1,23,456.78``) transparently because we
    simply remove every comma before parsing — the grouping style is
    informational only. Returns :class:`Decimal` rather than ``float``
    to preserve exact decimal equality (``Decimal("0.1") + Decimal("0.2")
    == Decimal("0.3")``) which matters for small percentages.

    Raises :class:`InvalidOperation` on malformed input; callers are
    expected to only hand this function strings that the master
    pattern already matched.
    """
    cleaned = number_text.replace(",", "").strip()
    return Decimal(cleaned)


def _parse_fiscal_year_yy(yy: int) -> int:
    """Expand a two-digit fiscal-year tail to a four-digit year.

    See :data:`_FY_PIVOT` for the pivot convention. ``FY99`` → ``1999``;
    ``FY00`` → ``2000``; ``FY49`` → ``2049``; ``FY50`` → ``1950``.
    """
    if yy < _FY_PIVOT:
        return _FY_CENTURY_RECENT + yy
    return _FY_CENTURY_LEGACY + yy


def _parse_fiscal_year(raw: str) -> int:
    """Normalise ``FY24`` / ``FY2024`` / ``FY 24`` to a 4-digit year."""
    digits = re.sub(r"\D", "", raw)  # strip 'FY' + whitespace
    if len(digits) == 2:
        return _parse_fiscal_year_yy(int(digits))
    if len(digits) == 4:
        return int(digits)
    # Should not occur — the master pattern only admits 2- or 4-digit tails.
    raise ValueError(f"Unparseable fiscal year: {raw!r}")


def _parse_fiscal_range(raw: str) -> int:
    """Normalise ``"2023-24"`` / ``"FY2023-24"`` to the ending year (``2024``).

    The 2-digit tail is interpreted within the same century as the
    4-digit head unless that would move the year **backwards**, in
    which case we roll to the next century — so ``"1999-00"`` maps
    to ``2000``, not ``1900``.
    """
    # Strip optional 'FY' prefix.
    stripped = re.sub(r"(?i)^FY\s?", "", raw).strip()
    head_str, tail_str = stripped.split("-", 1)
    head = int(head_str)
    tail = int(tail_str)
    head_century = (head // 100) * 100
    candidate = head_century + tail
    if candidate <= head:
        candidate += 100
    return candidate


def _parse_fiscal_quarter(raw: str) -> Decimal:
    """Normalise ``"Q1 FY25"`` / ``"Q2FY2026"`` to ``fy*10 + quarter``."""
    # The quarter digit always sits at index 1 (right after 'Q').
    quarter = int(raw[1])
    # Everything after 'Q<d>' is the FY tail — re-use the FY parser.
    fy_tail = raw[2:].strip()
    year = _parse_fiscal_year(fy_tail)
    return Decimal(year * 10 + quarter)


def _parse_currency_or_mult(
    raw: str, kind: Literal["inr", "usd", "mult_only"]
) -> tuple[Decimal, NumericUnit]:
    """Parse ``₹1,234.56 Cr`` / ``$1,234.56`` / ``1.2 Cr`` etc.

    Returns ``(canonical_value, unit)`` with the multiplier already
    applied so downstream comparison is unit-free within each unit
    class.
    """
    # Lowercase view for suffix sniffing; ``.lower()`` is cheap and
    # keeps the ``IGNORECASE`` logic explicit here rather than relying
    # on captured-group inspection.
    lowered = raw.lower()

    # Strip currency prefix if present.
    body_start = 0
    if kind == "inr":
        # Match ``₹`` (multi-byte) or ``rs.`` / ``rs`` / ``inr `` at the
        # start; the length depends on which one matched.
        match = re.match(r"(?i)^(?:₹|rs\.?|inr\s)\s?", raw)
        body_start = match.end() if match else 0
    elif kind == "usd":
        match = re.match(r"(?i)^(?:\$|usd\s)\s?", raw)
        body_start = match.end() if match else 0

    body = raw[body_start:].strip()

    # Sniff suffix.
    multiplier: Decimal = Decimal(1)
    if re.search(r"(?i)(?:crores?|\bcr)\b", lowered):
        multiplier = _CRORE_MULT
        body = re.sub(r"(?i)\s?(?:crores?|cr)\s*$", "", body).strip()
    elif re.search(r"(?i)(?:lakhs?|\bl)\b", lowered):
        multiplier = _LAKH_MULT
        body = re.sub(r"(?i)\s?(?:lakhs?|l)\s*$", "", body).strip()

    value = _strip_grouping(body) * multiplier

    if kind == "inr":
        # Indian currency keeps its unit even with a lakh/crore suffix —
        # callers comparing against a chunk written in ``Cr`` vs ``lakh``
        # want the magnitudes to match, and the unit stays ``INR``.
        return value, "INR"
    if kind == "usd":
        return value, "USD"
    # mult_only — no currency marker, so we tag it ``count_or_inr``
    # (see module docstring for the rationale).
    return value, "count_or_inr"


def _parse_percent(raw: str) -> Decimal:
    """Parse ``"2.5%"`` / ``"2.5 percent"`` / ``"2.5 pct"`` to ``2.5``."""
    body = re.sub(r"(?i)\s?(?:%|percent|pct)\s*$", "", raw).strip()
    return _strip_grouping(body)


def extract_numeric_tokens(text: str) -> list[NumericToken]:
    """Extract every numeric token from ``text``.

    The returned list preserves source order and has no overlapping
    spans — ``re.finditer`` already guarantees non-overlap, and the
    alternation in :data:`_MASTER_PATTERN` is ordered so longer
    shapes win over shorter ones sharing a prefix.

    Tokens that fail to parse (e.g. a captured grouping that
    :class:`Decimal` rejects) are skipped silently — the validator
    is only interested in claims that **can** be compared; an
    unparseable string is not a hallucination signal.
    """
    tokens: list[NumericToken] = []
    for match in _MASTER_PATTERN.finditer(text):
        raw = match.group(0)
        start, end = match.span()
        kind = match.lastgroup  # which named alternative matched
        try:
            value, unit = _dispatch_parse(raw, kind or "")
        except (InvalidOperation, ValueError):
            # The master pattern matched but decimal conversion failed
            # (e.g. a malformed grouping like ``"1,2,3"``). Skip rather
            # than fail — this is deterministic text, not user input,
            # so a parse failure is a regression we want logs to
            # surface via the caller's structured logger.
            continue
        tokens.append(
            NumericToken(
                value=value,
                unit=unit,
                original_text=raw,
                start_offset=start,
                end_offset=end,
            )
        )
    return tokens


def _dispatch_parse(raw: str, kind: str) -> tuple[Decimal, NumericUnit]:
    """Dispatch a matched substring to the right parser."""
    if kind == "fiscal_quarter":
        return _parse_fiscal_quarter(raw), "fiscal_quarter"
    if kind == "fiscal_range":
        return Decimal(_parse_fiscal_range(raw)), "fiscal_year"
    if kind == "fiscal_year":
        return Decimal(_parse_fiscal_year(raw)), "fiscal_year"
    if kind == "inr":
        return _parse_currency_or_mult(raw, "inr")
    if kind == "usd":
        return _parse_currency_or_mult(raw, "usd")
    if kind == "mult_only":
        return _parse_currency_or_mult(raw, "mult_only")
    if kind == "percent":
        return _parse_percent(raw), "percent"
    if kind == "bare":
        return _strip_grouping(raw), "number"
    raise ValueError(f"Unknown token kind: {kind!r}")


# --------------------------------------------------------------------------- #
# Validator                                                                   #
# --------------------------------------------------------------------------- #


@runtime_checkable
class _ChunkLike(Protocol):
    """Minimal duck-typed chunk: anything with ``.text`` satisfies.

    In production the validator is handed ``ChunkRecord``
    (:mod:`src.research.providers.base`) or ``ChunkHit.chunk``; in
    tests it may be a dataclass or a plain ``SimpleNamespace``. The
    protocol keeps the validator from taking a hard dependency on
    the ``ChunkRecord`` Pydantic model and keeps unit tests mock-free.
    """

    text: str


def _tokens_match(
    brief_token: NumericToken,
    chunk_token: NumericToken,
    *,
    epsilon: float,
) -> bool:
    """True when the two tokens are equivalent within ``epsilon``.

    Only tokens of the **same unit class** are comparable:

    * ``fiscal_year`` / ``fiscal_quarter`` require exact integer
      equality — a one-year drift in FY is a meaningful hallucination,
      not a rounding error.
    * ``number`` matches both itself and ``count_or_inr`` because a
      bare number in a chunk may be the textual rendering of a
      ``"1.2 Cr"`` token in the brief (``12000000`` vs ``"1.2 Cr"``
      are the same quantity) and vice versa.
    * ``INR`` / ``USD`` / ``count_or_inr`` all compare against each
      other when magnitudes match — callers writing a chunk as
      ``"₹1,234 Cr"`` and a brief as ``"1,234 Cr"`` want the match.
    * ``percent`` only compares against ``percent``.
    """
    a, b = brief_token.unit, chunk_token.unit

    # Fiscal shapes: exact equality only. ``fiscal_quarter`` uses the
    # synthetic ``fy*10 + q`` scalar so equality implies both year
    # and quarter match.
    if a in ("fiscal_year", "fiscal_quarter") or b in ("fiscal_year", "fiscal_quarter"):
        if a != b:
            return False
        return brief_token.value == chunk_token.value

    # Percent only compares with percent.
    if a == "percent" or b == "percent":
        if a != b:
            return False
        return _within_epsilon(brief_token.value, chunk_token.value, epsilon)

    # Monetary + count_or_inr + number: all magnitude-comparable.
    return _within_epsilon(brief_token.value, chunk_token.value, epsilon)


def _within_epsilon(a: Decimal, b: Decimal, epsilon: float) -> bool:
    """Relative epsilon with an absolute floor for values near zero.

    Relative tolerance is the right default at large magnitudes (a 1%
    drift on ``₹1,000 Cr`` is meaningful at ``₹10 Cr``), but near zero
    any non-zero drift is infinite in relative terms. We therefore
    apply ``epsilon`` as an **absolute** tolerance whenever the larger
    of the two magnitudes is below 1.0 — which is the regime where
    percentages and small decimals live. At larger magnitudes we use
    a pure relative tolerance.
    """
    if a == b:
        return True
    diff = abs(a - b)
    eps = Decimal(str(epsilon))
    largest = max(abs(a), abs(b))
    if largest < Decimal(1):
        return diff <= eps
    return diff <= eps * largest


class NumericValidator:
    """Configurable numeric-fidelity validator (design §3.8, Req 16.26).

    Parameters
    ----------
    epsilon:
        Relative tolerance for numeric-match comparisons. The default
        :data:`DEFAULT_EPSILON` (``0.01`` = 1%) is suitable for every
        unit class; override to tighten or loosen per deployment.
        Typically sourced from ``research.retrieval.*`` config once
        the loader wiring lands.

    Notes
    -----
    The class is stateless beyond ``epsilon`` so a single instance can
    be shared across concurrent runs. Construction is cheap — no
    regex compilation happens per-instance because
    :data:`_MASTER_PATTERN` is module-level.
    """

    def __init__(self, *, epsilon: float = DEFAULT_EPSILON) -> None:
        if epsilon < 0:
            raise ValueError(f"epsilon must be non-negative, got {epsilon}")
        self._epsilon = float(epsilon)

    @property
    def epsilon(self) -> float:
        """Return the configured relative tolerance."""
        return self._epsilon

    def validate(
        self,
        *,
        brief: "Mapping[str, str] | object",
        cited_chunks: Iterable[_ChunkLike],
    ) -> list[UnsupportedClaim]:
        """Validate ``brief`` against ``cited_chunks``; return violations.

        Parameters
        ----------
        brief:
            Either a plain ``dict[str, str]`` mapping section name
            to ``content_md``, or any object exposing the
            ``ResearchBrief`` section attributes (``summary``,
            ``thesis``, ``risks``, ``financial_highlights``,
            ``management_commentary``, ``technical_view``, ``peers``,
            ``macro_context``). Duck-typed so Task 13.8 can pass the
            real Pydantic model unchanged.
        cited_chunks:
            Iterable of chunk-like objects exposing a ``.text`` field.
            In production this is ``[hit.chunk for hit in
            retrieved_hits]`` or the ``ChunkRecord`` instances stored
            alongside the run. The validator only reads ``.text`` —
            embeddings, symbols, and user_ids are ignored here
            (citation-level user-scoping is the citation validator's
            job, Task 11.2).

        Returns
        -------
        list[UnsupportedClaim]
            One entry per brief-side numeric token that could not be
            matched within ``epsilon`` in any cited chunk. The list
            is empty when every token resolves, which is the common
            case for well-synthesised briefs.
        """
        sections = _coerce_brief_sections(brief)

        # Pre-extract chunk tokens once — the brief-side loop then
        # iterates over O(sections * tokens_per_section) brief tokens
        # against O(chunks * tokens_per_chunk) chunk tokens. For a
        # typical brief (8 sections, ~20 tokens/section, 40 cited
        # chunks, ~10 tokens/chunk) that's ~64k comparisons; each
        # comparison is a single Decimal subtraction. This is well
        # under the deterministic-validator budget in design §15.
        chunk_tokens: list[NumericToken] = []
        for chunk in cited_chunks:
            chunk_tokens.extend(extract_numeric_tokens(chunk.text))

        violations: list[UnsupportedClaim] = []
        for section_name, content in sections.items():
            if not content:
                continue
            for token in extract_numeric_tokens(content):
                if any(
                    _tokens_match(token, ct, epsilon=self._epsilon)
                    for ct in chunk_tokens
                ):
                    continue
                violations.append(
                    UnsupportedClaim(
                        section=section_name,
                        claim_text=token.original_text,
                        start_offset=token.start_offset,
                        end_offset=token.end_offset,
                        reason="numeric_drift",
                    )
                )
        return violations


def validate_numeric_fidelity(
    *,
    brief: "Mapping[str, str] | object",
    cited_chunks: Iterable[_ChunkLike],
    epsilon: float = DEFAULT_EPSILON,
) -> list[UnsupportedClaim]:
    """Module-level convenience wrapper around :class:`NumericValidator`.

    Intended for call sites that do not need a persistent validator
    instance — chiefly the Orchestrator's per-run numeric check
    (design §3.5, §12) and the offline rule-based judge
    (design §11.4). Equivalent to::

        NumericValidator(epsilon=epsilon).validate(
            brief=brief, cited_chunks=cited_chunks
        )
    """
    return NumericValidator(epsilon=epsilon).validate(
        brief=brief, cited_chunks=cited_chunks
    )


# --------------------------------------------------------------------------- #
# Brief-section coercion                                                      #
# --------------------------------------------------------------------------- #


# Canonical section list per design §3.5 / Req 1.5. Kept private so
# we don't fight the eventual ``ResearchBrief`` Pydantic model over
# ownership of the section name list; when that model lands, the
# duck-typed path below reads the same fields from the real object.
_BRIEF_SECTION_NAMES: Final[tuple[str, ...]] = (
    "summary",
    "thesis",
    "risks",
    "financial_highlights",
    "management_commentary",
    "technical_view",
    "peers",
    "macro_context",
)


def _coerce_brief_sections(
    brief: "Mapping[str, str] | object",
) -> dict[str, str]:
    """Normalise accepted brief inputs into ``{section_name: content}``.

    * ``Mapping[str, str]`` — returned as a plain ``dict`` (filters
      out ``None`` values but preserves every user-supplied section
      name so the validator is useful for partial briefs and for
      tests that construct a single-section input).
    * Any object — each canonical section name is looked up via
      :func:`getattr`; missing attributes are skipped silently so a
      ``ResearchBrief`` carrying a subset of sections (e.g. from a
      ``partial=true`` run, Req 1.6) still validates cleanly.
    """
    if isinstance(brief, Mapping):
        return {
            str(name): str(content)
            for name, content in brief.items()
            if content is not None
        }
    coerced: dict[str, str] = {}
    for name in _BRIEF_SECTION_NAMES:
        value = getattr(brief, name, None)
        if isinstance(value, str) and value:
            coerced[name] = value
    return coerced
