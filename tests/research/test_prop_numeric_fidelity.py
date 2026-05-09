"""Numeric fidelity — design §17.1 Property 9 / Req 14.10, Req 16.26.

The invariant under test: **the numeric-fidelity validator flags every
numeric value in a** ``Research_Brief`` **that is not within ``epsilon``
of at least one cited chunk, and never flags one that is.**

This is Property 9 in the design traceability table (design §17.1) and
directly validates Requirement 14.10 together with Requirement 16.26.
It complements the example-driven suite in ``test_numeric_validator.py``
— the examples nail down specific shapes (``₹1,234.56``, ``1.2 Cr``,
``FY24``, ``Q1 FY25``) whereas this file asserts the same invariant
holds across **every** generated shape combination.

Two complementary properties
----------------------------
The Property 9 description decomposes cleanly into two direction-
specific claims, each expressed as its own Hypothesis test so a
failure message points at the right half of the invariant:

1. **Positive** (``test_matching_brief_yields_no_violations``) — if
   every numeric atom in the brief has a matching counterpart in the
   cited chunks (same unit class, within ``epsilon``), the validator
   returns ``[]``. Protects against spurious ``numeric_drift``
   violations; a failure means the validator is over-flagging.
2. **Negative** (``test_mismatched_atom_is_always_flagged``) — if a
   brief contains at least one "rogue" numeric atom that has **no**
   equivalent in any cited chunk, the validator emits at least one
   ``UnsupportedClaim`` whose ``claim_text`` corresponds to that
   rogue atom. Protects against silent pass-through of hallucinated
   numbers; a failure means the validator is under-flagging.

Strategy design
---------------
The smallest unit we generate is a ``_NumericAtom`` — a canonical
``(value, unit)`` pair plus an ``_AtomRenderer`` that knows how to
emit one or more textual renderings of the same atom (``"₹1,234 Cr"``
and the raw-integer rendering ``"12340000000"`` render the same
atom; ``"FY24"`` has only one textual form). Briefs and chunks are
then composed from these atoms with realistic filler text, so the
tokenizer in ``numeric_validator.py`` sees the same Indian-filing
conventions it meets in production.

Why atoms + renderers rather than direct text generation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Generating raw text and then asserting the validator's output would
require the test to **reimplement the tokenizer** to decide whether
the generated string actually contains a numeric token — which would
be circular. By working in canonical ``(value, unit)`` space we:

* Know up front, by construction, which atoms the validator should
  match and which it should flag.
* Keep Hypothesis's shrinker effective — shrinking a ``Decimal`` is
  well-understood; shrinking a free-form string of "maybe contains
  a number" is not.
* Let the renderers test every surface shape the tokenizer is
  advertised to handle (design §3.8 bullets): ``₹``, ``Cr``, ``lakh``,
  ``%``, ``FY``, ``Q1 FY``, bare decimals.

Shape coverage
~~~~~~~~~~~~~~
``_ATOM_KINDS`` enumerates every unit class the validator supports
plus every matching-form pair the positive test must exercise:

* ``inr_cr``: ``₹<N> Cr`` paired with raw-integer rendering.
* ``inr_lakh``: ``₹<N> lakh`` paired with raw-integer rendering.
* ``inr_plain``: ``₹<N>`` paired with ``Rs. <N>``.
* ``usd_plain``: ``$<N>`` paired with raw ``<N>``.
* ``percent``: ``<N>%`` paired with ``<N> percent``.
* ``count_cr``: ``<N> Cr`` (no currency) paired with raw-integer.
* ``count_lakh``: ``<N> lakh`` (no currency) paired with raw-integer.
* ``fiscal_year``: ``FY<YY>`` paired with ``FY<YYYY>``.
* ``fiscal_quarter``: ``Q<d> FY<YY>`` paired with ``Q<d>FY<YYYY>``.

Hypothesis configuration
~~~~~~~~~~~~~~~~~~~~~~~~
``max_examples=150`` gives good shape coverage without blowing CI
wall-time (each example is a few microseconds of regex + Decimal
arithmetic). ``deadline=None`` prevents flakes from cold-start regex
compile cost. ``suppress_health_check=[HealthCheck.too_slow]`` is
disabled — we want the health check on, because generator slowness
here would indicate a real regression in the atom/renderer pair.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Literal

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from src.research.validators.numeric_validator import (
    DEFAULT_EPSILON,
    NumericValidator,
    validate_numeric_fidelity,
)
from src.research.validators.types import UnsupportedClaim


# --------------------------------------------------------------------------- #
# Atom model                                                                  #
# --------------------------------------------------------------------------- #


# Discriminator for the shape the atom is rendered in. The validator
# compares tokens by **unit class** (INR / USD / percent / count_or_inr
# / fiscal_year / fiscal_quarter / number) within a relative epsilon;
# every kind below belongs to exactly one such unit class, which lets
# the positive test choose "matching" renderings that are guaranteed
# to cross-match the validator's comparator.
_AtomKind = Literal[
    "inr_cr",
    "inr_lakh",
    "inr_plain",
    "usd_plain",
    "percent",
    "count_cr",
    "count_lakh",
    "fiscal_year",
    "fiscal_quarter",
]


@dataclass(frozen=True)
class _NumericAtom:
    """Canonical ``(kind, value)`` pair plus the factor-1 magnitude."""

    kind: _AtomKind
    # ``value`` is the **canonical** magnitude the validator produces
    # after parsing any of the atom's renderings (e.g. ``1.2 Cr`` →
    # ``12_000_000`` for kind ``count_cr``). Percent is the percent
    # value itself; fiscal-year is the 4-digit year; fiscal-quarter
    # is the synthetic ``fy*10 + q`` scalar per the validator's
    # comment. We keep this in sync with the validator's semantics
    # so a rendering that parses back to ``value`` is guaranteed to
    # cross-match.
    value: Decimal


# --------------------------------------------------------------------------- #
# Renderers                                                                   #
# --------------------------------------------------------------------------- #
#
# Each renderer returns a textual form of the atom that the validator
# is advertised to parse (design §3.8). For most kinds we provide a
# *primary* renderer (the "obvious" shape a human would write) and a
# *secondary* renderer that expresses the same canonical value in a
# different surface form — the positive test deliberately puts one
# rendering in the brief and the other in the cited chunk to prove
# the cross-shape match path in ``_tokens_match`` actually fires.


def _render_inr_cr(value: Decimal) -> str:
    """``₹1,234 Cr`` — rupee prefix + crore suffix.

    ``value`` is the **expanded** rupee amount (so ``12_000_000`` →
    ``₹1.2 Cr``). We divide by the crore multiplier (1e7) and render
    with up to 4 decimal places, trimming trailing zeros for a clean
    shape. The tokenizer parses either ``₹1,234.5 Cr`` or
    ``₹1234.5 Cr`` equivalently, so we skip the grouping commas to
    keep the output simple and shrinkable.
    """
    cr_value = value / Decimal("10000000")
    text = _format_decimal(cr_value, max_places=4)
    return f"\u20B9{text} Cr"


def _render_raw_int(value: Decimal) -> str:
    """Raw integer rendering of ``value`` — used as the cross-shape match.

    Used as the secondary rendering for ``inr_cr``, ``inr_lakh``,
    ``count_cr``, and ``count_lakh``. The validator's cross-shape
    match (``count_or_inr`` ↔ ``INR`` / ``number``) is what makes
    ``12000000`` in a chunk satisfy ``₹1.2 Cr`` in the brief.
    """
    # Quantize to zero decimal places; the test-side atoms are always
    # integer crore / lakh multiples, so this is lossless.
    return str(int(value))


def _render_inr_lakh(value: Decimal) -> str:
    """``₹2.5 lakh`` — rupee prefix + lakh suffix."""
    lakh_value = value / Decimal("100000")
    text = _format_decimal(lakh_value, max_places=4)
    return f"\u20B9{text} lakh"


def _render_inr_plain(value: Decimal) -> str:
    """``₹1,234.56`` — rupee prefix only, no multiplier."""
    return f"\u20B9{_format_decimal(value, max_places=2)}"


def _render_rs_plain(value: Decimal) -> str:
    """``Rs. 1,234.56`` — alternate rupee prefix, same magnitude."""
    return f"Rs. {_format_decimal(value, max_places=2)}"


def _render_usd_plain(value: Decimal) -> str:
    """``$1,234.56`` — dollar prefix."""
    return f"${_format_decimal(value, max_places=2)}"


def _render_percent(value: Decimal) -> str:
    """``2.5%`` — percent sign."""
    return f"{_format_decimal(value, max_places=2)}%"


def _render_percent_word(value: Decimal) -> str:
    """``2.5 percent`` — spelled-out percent."""
    return f"{_format_decimal(value, max_places=2)} percent"


def _render_count_cr(value: Decimal) -> str:
    """``1.2 Cr`` — crore suffix, no currency."""
    cr_value = value / Decimal("10000000")
    return f"{_format_decimal(cr_value, max_places=4)} Cr"


def _render_count_lakh(value: Decimal) -> str:
    """``2.5 lakh`` — lakh suffix, no currency."""
    lakh_value = value / Decimal("100000")
    return f"{_format_decimal(lakh_value, max_places=4)} lakh"


def _render_fy_two_digit(year: Decimal) -> str:
    """``FY24`` — two-digit fiscal year."""
    yy = int(year) % 100
    return f"FY{yy:02d}"


def _render_fy_four_digit(year: Decimal) -> str:
    """``FY2024`` — four-digit fiscal year."""
    return f"FY{int(year):04d}"


def _render_fq_spaced(scalar: Decimal) -> str:
    """``Q1 FY25`` — quarter with space + two-digit FY."""
    fq_int = int(scalar)
    quarter = fq_int % 10
    year = fq_int // 10
    return f"Q{quarter} FY{year % 100:02d}"


def _render_fq_compact(scalar: Decimal) -> str:
    """``Q1FY2025`` — quarter + four-digit FY, no space."""
    fq_int = int(scalar)
    quarter = fq_int % 10
    year = fq_int // 10
    return f"Q{quarter}FY{year:04d}"


def _format_decimal(value: Decimal, *, max_places: int) -> str:
    """Render a ``Decimal`` with up to ``max_places`` places, no trailing zeros.

    ``Decimal.normalize()`` would also drop trailing zeros but can
    switch to scientific notation for small magnitudes — unwanted in
    a test that is comparing substrings. We do the formatting by hand
    so every rendered shape lives in the grammar the tokenizer
    accepts.
    """
    quantized = value.quantize(Decimal(10) ** -max_places)
    text = format(quantized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


# Primary / secondary renderer pairs per atom kind. Both renderings
# must parse back to the same canonical ``value`` so the positive
# test is well-defined — the pair is the test-side proof that the
# validator's cross-shape match path works.
_RENDERERS: dict[_AtomKind, tuple[Callable[[Decimal], str], Callable[[Decimal], str]]] = {
    "inr_cr":          (_render_inr_cr, _render_raw_int),
    "inr_lakh":        (_render_inr_lakh, _render_raw_int),
    "inr_plain":       (_render_inr_plain, _render_rs_plain),
    "usd_plain":       (_render_usd_plain, _render_usd_plain),
    "percent":         (_render_percent, _render_percent_word),
    "count_cr":        (_render_count_cr, _render_raw_int),
    "count_lakh":      (_render_count_lakh, _render_raw_int),
    "fiscal_year":     (_render_fy_two_digit, _render_fy_four_digit),
    "fiscal_quarter":  (_render_fq_spaced, _render_fq_compact),
}


# --------------------------------------------------------------------------- #
# Hypothesis strategies — atom generation                                     #
# --------------------------------------------------------------------------- #


def _atom_strategy(kind: _AtomKind) -> st.SearchStrategy[_NumericAtom]:
    """Build a ``_NumericAtom`` strategy for a given kind.

    Value ranges are chosen so:

    * Magnitudes stay well inside ``Decimal`` precision.
    * All renderings parse back to **exactly** the same canonical
      value (no rounding loss round-tripping ``12_000_000`` →
      ``"1.2 Cr"`` → ``12_000_000``).
    * Shrinking lands on the simplest atom in the class (``value=1``
      for numeric kinds, ``FY2024`` for fiscal_year, ``Q1 FY2024``
      for fiscal_quarter).
    """
    if kind == "inr_cr":
        # 1 Cr – 9999 Cr expressed as expanded rupees (1e7 – 9.999e10).
        # Step of 1e6 (10 lakh) so ``value / 1e7`` is always a clean
        # 4-decimal quantity that renders without rounding loss.
        return st.integers(min_value=10, max_value=99_990).map(
            lambda n: _NumericAtom(kind="inr_cr", value=Decimal(n) * Decimal(1_000_000))
        )
    if kind == "inr_lakh":
        # 1 lakh – 999 lakh expressed as expanded rupees (1e5 – 9.99e7).
        return st.integers(min_value=10, max_value=99_900).map(
            lambda n: _NumericAtom(kind="inr_lakh", value=Decimal(n) * Decimal(10_000))
        )
    if kind == "inr_plain":
        # Small rupee amounts with up to two decimal places.
        return st.decimals(
            min_value=Decimal("1"),
            max_value=Decimal("99999.99"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ).map(lambda v: _NumericAtom(kind="inr_plain", value=v))
    if kind == "usd_plain":
        return st.decimals(
            min_value=Decimal("1"),
            max_value=Decimal("99999.99"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ).map(lambda v: _NumericAtom(kind="usd_plain", value=v))
    if kind == "percent":
        # 0.1% – 99.99% — avoiding zero keeps the relative-epsilon
        # comparator in its normal regime.
        return st.decimals(
            min_value=Decimal("0.1"),
            max_value=Decimal("99.99"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ).map(lambda v: _NumericAtom(kind="percent", value=v))
    if kind == "count_cr":
        return st.integers(min_value=10, max_value=99_990).map(
            lambda n: _NumericAtom(kind="count_cr", value=Decimal(n) * Decimal(1_000_000))
        )
    if kind == "count_lakh":
        return st.integers(min_value=10, max_value=99_900).map(
            lambda n: _NumericAtom(kind="count_lakh", value=Decimal(n) * Decimal(10_000))
        )
    if kind == "fiscal_year":
        # 2000-2049 so both 2-digit and 4-digit renderings parse to
        # the same year under the validator's FY-pivot rule
        # (``_FY_PIVOT=50`` → ``FY24`` == ``2024``).
        return st.integers(min_value=2000, max_value=2049).map(
            lambda y: _NumericAtom(kind="fiscal_year", value=Decimal(y))
        )
    # fiscal_quarter
    # Synthetic scalar ``fy*10 + q`` per the validator's convention.
    return st.tuples(
        st.integers(min_value=2000, max_value=2049),
        st.integers(min_value=1, max_value=4),
    ).map(
        lambda pair: _NumericAtom(
            kind="fiscal_quarter",
            value=Decimal(pair[0] * 10 + pair[1]),
        )
    )


# A single strategy that generates atoms across **every** kind; used
# to seed matching-brief generation so one test case may mix e.g.
# ``₹1,234 Cr``, ``FY24``, ``12.5%``, and ``Q1 FY23``.
_any_atom = st.one_of(
    _atom_strategy("inr_cr"),
    _atom_strategy("inr_lakh"),
    _atom_strategy("inr_plain"),
    _atom_strategy("usd_plain"),
    _atom_strategy("percent"),
    _atom_strategy("count_cr"),
    _atom_strategy("count_lakh"),
    _atom_strategy("fiscal_year"),
    _atom_strategy("fiscal_quarter"),
)


# --------------------------------------------------------------------------- #
# Text composition                                                            #
# --------------------------------------------------------------------------- #


# Filler phrases used to stitch atoms into naturalistic sentences.
# Kept deliberately free of digits or currency symbols so the
# tokenizer cannot pull an accidental extra token out of the filler.
# Each phrase ends with a trailing space so atom-insertion is seamless.
_FILLER_BEFORE: tuple[str, ...] = (
    "The company reported ",
    "Management noted ",
    "Revenue of ",
    "Segment delivered ",
    "Guidance implies ",
)
_FILLER_BETWEEN: tuple[str, ...] = (
    ". Further, ",
    " and ",
    "; subsequently, ",
    ". Meanwhile, ",
)
_FILLER_AFTER: tuple[str, ...] = (
    " during the period.",
    " for the segment.",
    " across regions.",
    " as disclosed.",
)


@st.composite
def _compose_text_from_atoms(
    draw: st.DrawFn,
    atoms: list[_NumericAtom],
    *,
    which_rendering: Literal["primary", "secondary", "either"] = "primary",
) -> str:
    """Stitch ``atoms`` into naturalistic text using filler phrases.

    ``which_rendering`` selects which of the renderer pair to use:

    * ``primary`` — always the primary renderer.
    * ``secondary`` — always the secondary renderer (different surface
      form but same canonical value).
    * ``either`` — draw independently per atom; exercises the
      positive test's "brief uses one shape, chunk uses the other"
      coverage path.
    """
    parts: list[str] = []
    for i, atom in enumerate(atoms):
        if i == 0:
            parts.append(draw(st.sampled_from(_FILLER_BEFORE)))
        else:
            parts.append(draw(st.sampled_from(_FILLER_BETWEEN)))
        primary, secondary = _RENDERERS[atom.kind]
        if which_rendering == "primary":
            renderer = primary
        elif which_rendering == "secondary":
            renderer = secondary
        else:
            renderer = draw(st.sampled_from((primary, secondary)))
        parts.append(renderer(atom.value))
    parts.append(draw(st.sampled_from(_FILLER_AFTER)))
    return "".join(parts)


# --------------------------------------------------------------------------- #
# Fake chunk                                                                  #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _FakeChunk:
    """Duck-typed chunk — the validator only reads ``.text``.

    Matches the helper used by the example-driven suite in
    ``test_numeric_validator.py``. Defined locally so this file is
    self-contained; the validator's :class:`_ChunkLike` protocol
    accepts anything with a ``.text`` attribute.
    """

    text: str


# --------------------------------------------------------------------------- #
# Rogue (mismatched) atom                                                     #
# --------------------------------------------------------------------------- #


def _rogue_atom(base: _NumericAtom) -> _NumericAtom:
    """Return an atom that must **not** match ``base`` under the validator.

    The rogue is constructed so the validator's ``_tokens_match``
    returns ``False`` for it against **every** rendering of ``base``:

    * **Fiscal shapes** — return a different fiscal year / quarter
      outside any plausible rounding window. The validator requires
      exact integer equality for fiscal kinds, so ``base.value + 1``
      is always a safe rogue.
    * **Percent** — return a percent value whose relative distance
      from ``base.value`` exceeds the default epsilon by a large
      margin (multiply by 3 and add 10, clamped into the
      ``percent`` range).
    * **Everything else** — scale ``base.value`` by 7 (well outside
      any sensible epsilon) so the relative-epsilon comparator
      rejects the pair cleanly.

    The rogue keeps the same ``kind`` as ``base`` so the validator
    cannot reject the match on a unit-class mismatch instead of a
    magnitude mismatch. That keeps the test honest: we are
    exercising the magnitude path, not the unit-class short-circuit.
    """
    if base.kind == "fiscal_year":
        rogue_year = int(base.value) + 5
        # Stay inside the FY-pivot-safe window the atom strategy uses.
        if rogue_year > 2049:
            rogue_year -= 10
        return _NumericAtom(kind="fiscal_year", value=Decimal(rogue_year))
    if base.kind == "fiscal_quarter":
        base_int = int(base.value)
        year = base_int // 10
        quarter = base_int % 10
        new_quarter = 4 if quarter == 1 else 1  # always distinct
        rogue_scalar = year * 10 + new_quarter
        return _NumericAtom(kind="fiscal_quarter", value=Decimal(rogue_scalar))
    if base.kind == "percent":
        # Guaranteed to shift by ≥ 10 percentage points; at most
        # ~99.99 by clamp. Relative distance is bounded well above
        # the 1% default epsilon regardless of base magnitude.
        rogue = base.value * Decimal(3) + Decimal(10)
        if rogue > Decimal("99.99"):
            rogue = Decimal("99.99") - base.value  # still ≠ base when base small
        return _NumericAtom(kind="percent", value=rogue)
    # Monetary / count kinds — scale by 7 to exceed any sane epsilon.
    return _NumericAtom(kind=base.kind, value=base.value * Decimal(7) + Decimal(1))


# --------------------------------------------------------------------------- #
# Property 9a — positive direction                                            #
# --------------------------------------------------------------------------- #


@st.composite
def _matching_brief_and_chunks(
    draw: st.DrawFn,
) -> tuple[dict[str, str], list[_FakeChunk]]:
    """Generate a brief whose every atom is also present in the chunks.

    The composition rule:

    * Draw ``n`` atoms (1..5) from the mixed-kind atom strategy.
    * Render the brief text using the **primary** renderer.
    * Render **each** atom into its own chunk using the **secondary**
      renderer so the positive test exercises the cross-shape match
      path (``₹1.2 Cr`` in the brief ↔ ``12000000`` in the chunk).
      Using per-atom chunks rather than one merged chunk also
      exercises the multi-chunk aggregation path in the validator.
    * Optionally append a filler "decoy" chunk with no numeric
      content, to confirm the validator does not rely on a specific
      chunk being the "numeric one".
    """
    n = draw(st.integers(min_value=1, max_value=5))
    atoms = draw(st.lists(_any_atom, min_size=n, max_size=n))

    # Brief sentence uses the primary rendering for every atom.
    brief_text = draw(_compose_text_from_atoms(atoms, which_rendering="primary"))
    # Arbitrary section name — the validator treats every key as a
    # section. We sample a canonical name from the spec so the
    # emitted ``UnsupportedClaim.section`` (on the negative test)
    # lands on a familiar value when a failure surfaces.
    section = draw(
        st.sampled_from(
            (
                "summary",
                "thesis",
                "financial_highlights",
                "management_commentary",
                "risks",
            )
        )
    )
    brief = {section: brief_text}

    # One chunk per atom, secondary rendering so surface form differs
    # from the brief wherever possible.
    chunks: list[_FakeChunk] = []
    for atom in atoms:
        chunk_text = draw(
            _compose_text_from_atoms([atom], which_rendering="secondary")
        )
        chunks.append(_FakeChunk(text=chunk_text))

    # Decoy chunk (probability 1/2) with zero numeric tokens.
    if draw(st.booleans()):
        chunks.append(_FakeChunk(text="No numerical content in this chunk."))

    return brief, chunks


@given(case=_matching_brief_and_chunks())
@settings(
    max_examples=150,
    deadline=None,
    # Composed strategies with multiple ``draw`` calls per example are
    # flagged as "data_too_large" by Hypothesis's default budget,
    # even though each example completes in microseconds. The
    # numeric content is the whole point of the property, so
    # suppress the size check rather than shrink the atom count.
    suppress_health_check=[HealthCheck.data_too_large],
)
def test_matching_brief_yields_no_violations(
    case: tuple[dict[str, str], list[_FakeChunk]],
) -> None:
    """Positive direction: matching atoms never produce a violation.

    Validates: Requirements 14.10, 16.26.

    For any brief whose numeric atoms all have a within-epsilon
    counterpart in the cited chunks, the validator returns an empty
    violation list. A failure here means the validator is
    over-flagging — either the cross-shape match path is broken (a
    regression on ``_tokens_match``) or the relative-epsilon
    comparator has drifted into rejecting known-good pairs.
    """
    brief, chunks = case
    violations = validate_numeric_fidelity(brief=brief, cited_chunks=chunks)
    # Hypothesis prints ``violations`` in the failure header via
    # ``repr`` so the failing atom shows up directly — no extra
    # message needed.
    assert violations == []


# --------------------------------------------------------------------------- #
# Property 9b — negative direction                                            #
# --------------------------------------------------------------------------- #


@st.composite
def _mismatched_brief_and_chunks(
    draw: st.DrawFn,
) -> tuple[dict[str, str], list[_FakeChunk], _NumericAtom]:
    """Generate a brief with a rogue atom absent from every cited chunk.

    Composition:

    * Draw ``k`` "good" atoms (0..3) that *will* be supported by
      chunks — exercises the validator's mixed-case path (some tokens
      match, one doesn't).
    * Draw one additional "rogue" atom whose value has no match among
      the chunks. The rogue is derived from a freshly-drawn base via
      :func:`_rogue_atom` so its kind is covered uniformly across
      every unit class the validator supports.
    * Render the brief with the **primary** renderer for every atom,
      in deterministic order (good atoms first, rogue last — the
      rogue's text is what the assertion expects to see flagged).
    * Render chunks for the good atoms only — the rogue has no chunk,
      which is the point of the test.

    Returns the rogue atom alongside so the assertion can inspect
    the ``claim_text`` offsets for that specific atom's rendering.
    """
    k = draw(st.integers(min_value=0, max_value=3))
    good_atoms = draw(st.lists(_any_atom, min_size=k, max_size=k))
    base = draw(_any_atom)
    rogue = _rogue_atom(base)

    # The rogue must not be matchable against any good atom under
    # the validator's comparator — otherwise the good atom's chunk
    # would legitimately support the rogue and the negative
    # assertion would (correctly) fail.
    #
    # The atom strategies are independent across kinds and values,
    # so collisions are possible in two ways:
    #
    # 1. Same unit class + equivalent value (fiscal / percent /
    #    monetary within epsilon).
    # 2. Cross-unit magnitude match: the validator treats every
    #    monetary-or-count kind (INR / USD / count_or_inr / number)
    #    as magnitude-comparable, so an ``inr_cr`` rogue with value
    #    ``12_000_000`` would match a ``count_cr`` good atom of the
    #    same magnitude.
    #
    # ``assume(False)`` discards colliding examples rather than
    # fabricating a fresh rogue, keeping the test's input-space
    # uniform. Collisions are rare across the nine-kind atom
    # universe and the numeric ranges used, so the ``filter_too_much``
    # health check is not at risk.
    if _rogue_collides_with_any(rogue, good_atoms):
        assume(False)

    # Render brief: good atoms then rogue, using primary renderer so
    # the rogue's expected substring is well-defined.
    all_atoms = [*good_atoms, rogue]
    brief_text = draw(_compose_text_from_atoms(all_atoms, which_rendering="primary"))
    section = draw(
        st.sampled_from(
            (
                "summary",
                "thesis",
                "financial_highlights",
                "management_commentary",
                "risks",
            )
        )
    )
    brief = {section: brief_text}

    # Chunks cover good atoms only.
    chunks: list[_FakeChunk] = []
    for atom in good_atoms:
        chunks.append(
            _FakeChunk(
                text=draw(
                    _compose_text_from_atoms([atom], which_rendering="secondary")
                )
            )
        )

    return brief, chunks, rogue


@given(case=_mismatched_brief_and_chunks())
@settings(
    max_examples=150,
    deadline=None,
    suppress_health_check=[HealthCheck.data_too_large],
)
def test_mismatched_atom_is_always_flagged(
    case: tuple[dict[str, str], list[_FakeChunk], _NumericAtom],
) -> None:
    """Negative direction: the rogue atom is always flagged.

    Validates: Requirements 14.10, 16.26.

    For any brief containing a numeric atom with no within-epsilon
    equivalent in the cited chunks, the validator must emit at least
    one ``UnsupportedClaim`` whose ``claim_text`` corresponds to the
    rogue atom's rendering. A failure here means the validator is
    under-flagging — a hallucinated numeric value could silently
    land in the final brief.

    The assertion has two legs:

    1. Every returned violation is an ``UnsupportedClaim`` with
       ``reason="numeric_drift"`` (shape check).
    2. At least one violation's ``claim_text`` parses back to the
       rogue atom's canonical value — i.e. the validator flagged the
       right token. We check via the validator's own extractor
       rather than string equality so minor stylistic choices
       (``₹1,234.56`` vs ``₹1234.56``) don't cause spurious test
       failures.
    """
    brief, chunks, rogue = case
    violations = validate_numeric_fidelity(brief=brief, cited_chunks=chunks)

    # Leg 1 — every violation has the expected shape.
    assert violations, (
        "Validator under-flagged: rogue atom "
        f"{rogue!r} produced no violations"
    )
    for v in violations:
        assert isinstance(v, UnsupportedClaim)
        assert v.reason == "numeric_drift"

    # Leg 2 — at least one violation corresponds to the rogue atom.
    # We parse each violation's ``claim_text`` through the
    # validator's own tokenizer and check for the rogue's canonical
    # ``(kind, value)`` using the same equivalence the validator
    # uses (unit class + exact/epsilon equality).
    from src.research.validators.numeric_validator import extract_numeric_tokens

    expected_unit = _canonical_unit_for_kind(rogue.kind)
    matched = False
    for v in violations:
        for token in extract_numeric_tokens(v.claim_text):
            if token.unit != expected_unit:
                continue
            if _values_equivalent(token.value, rogue.value, rogue.kind):
                matched = True
                break
        if matched:
            break
    assert matched, (
        "Validator flagged a violation but not for the rogue atom. "
        f"rogue={rogue!r}, violations={violations!r}"
    )


# --------------------------------------------------------------------------- #
# Helpers for rogue-verification                                              #
# --------------------------------------------------------------------------- #


# Unit classes the validator treats as magnitude-comparable with each
# other — i.e. a brief-side token in any of these classes can match a
# chunk-side token in any other class purely on magnitude. Derived
# directly from the fall-through branch in ``_tokens_match`` (design
# §3.8): fiscal shapes and ``percent`` require exact unit equality;
# everything else is pooled.
_MAGNITUDE_COMPARABLE_UNITS: frozenset[str] = frozenset(
    {"INR", "USD", "count_or_inr", "number"}
)


def _rogue_collides_with_any(
    rogue: _NumericAtom, good_atoms: list[_NumericAtom]
) -> bool:
    """True iff ``rogue`` is matchable against any entry in ``good_atoms``.

    Mirrors the unit-class logic in
    :func:`src.research.validators.numeric_validator._tokens_match`
    so the negative-test's assume() is perfectly correlated with the
    validator's own comparator — a rogue we *don't* discard is
    guaranteed to be un-matchable.
    """
    rogue_unit = _canonical_unit_for_kind(rogue.kind)
    for good in good_atoms:
        good_unit = _canonical_unit_for_kind(good.kind)
        if rogue_unit in ("fiscal_year", "fiscal_quarter") or good_unit in (
            "fiscal_year",
            "fiscal_quarter",
        ):
            if rogue_unit != good_unit:
                continue
            if rogue.value == good.value:
                return True
            continue
        if rogue_unit == "percent" or good_unit == "percent":
            if rogue_unit != good_unit:
                continue
            if _values_equivalent(rogue.value, good.value, "percent"):
                return True
            continue
        # Magnitude-comparable pool.
        if (
            rogue_unit in _MAGNITUDE_COMPARABLE_UNITS
            and good_unit in _MAGNITUDE_COMPARABLE_UNITS
        ):
            # Any non-fiscal, non-percent kind works here — we pass
            # ``rogue.kind`` purely to select the epsilon regime, not
            # to enforce kind equality.
            if _values_equivalent(rogue.value, good.value, rogue.kind):
                return True
    return False


def _canonical_unit_for_kind(kind: _AtomKind) -> str:
    """Map a test-side ``_AtomKind`` to the validator's unit class.

    The validator uses a coarser unit ontology than the test's atom
    kinds (both ``inr_cr`` and ``inr_plain`` collapse to ``"INR"``;
    both ``count_cr`` and ``count_lakh`` collapse to
    ``"count_or_inr"``). This helper makes that mapping explicit so
    the negative test's "did the validator flag the right token?"
    check lines up with the validator's own comparator.
    """
    mapping: dict[_AtomKind, str] = {
        "inr_cr":          "INR",
        "inr_lakh":        "INR",
        "inr_plain":       "INR",
        "usd_plain":       "USD",
        "percent":         "percent",
        "count_cr":        "count_or_inr",
        "count_lakh":      "count_or_inr",
        "fiscal_year":     "fiscal_year",
        "fiscal_quarter":  "fiscal_quarter",
    }
    return mapping[kind]


def _values_equivalent(a: Decimal, b: Decimal, kind: _AtomKind) -> bool:
    """Canonical-value equivalence for rogue-verification.

    Fiscal kinds require exact integer equality; numeric kinds
    tolerate the default relative epsilon (matching the validator's
    own behaviour) — we do *not* need tighter tolerance here because
    the rogue atom is constructed to fall well outside epsilon.
    """
    if kind in ("fiscal_year", "fiscal_quarter"):
        return a == b
    if a == b:
        return True
    eps = Decimal(str(DEFAULT_EPSILON))
    largest = max(abs(a), abs(b))
    diff = abs(a - b)
    if largest < Decimal(1):
        return diff <= eps
    return diff <= eps * largest


# --------------------------------------------------------------------------- #
# Metamorphic property: per-instance NumericValidator matches helper          #
# --------------------------------------------------------------------------- #


@given(case=_matching_brief_and_chunks())
@settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.data_too_large],
)
def test_validator_instance_matches_module_helper(
    case: tuple[dict[str, str], list[_FakeChunk]],
) -> None:
    """``NumericValidator().validate`` ≡ ``validate_numeric_fidelity``.

    Validates: Requirements 14.10, 16.26 — the module-level
    convenience wrapper is the same function as the class method
    under the default epsilon, which is what every caller in the
    spec relies on. Drives the matching case so both paths should
    return ``[]`` together; any divergence points at a regression in
    the convenience wrapper's delegation.
    """
    brief, chunks = case
    instance_result = NumericValidator().validate(
        brief=brief, cited_chunks=chunks
    )
    helper_result = validate_numeric_fidelity(brief=brief, cited_chunks=chunks)
    assert instance_result == helper_result == []
