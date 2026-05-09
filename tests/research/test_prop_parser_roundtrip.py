"""Parser round-trip — design §17.1 Property 5 / Req 14.5, Req 10.3.

The invariant under test: **the canonical pretty-printer is the inverse
of the canonical parser, modulo whitespace normalisation.** Concretely,
for any :class:`~src.research.ingest.parser.canonical.CanonicalDoc` the
round-trip

.. code-block:: text

    parse_canonical(pretty_print(doc)) ≡ doc

must hold, where ``≡`` is defined as:

1. All fields other than ``canonical_text`` are equal on the dump
   (``model_dump(exclude={"canonical_text"})``).
2. ``canonical_text`` is equal after running both sides through
   :func:`~src.research.ingest.parser.canonical._normalise_for_equality`,
   the helper that codifies the whitespace normalisations the
   pretty-printer is permitted to introduce (folded line endings,
   trimmed trailing whitespace, collapsed blank-line runs, enforced
   single trailing newline).

This is Property 5 in the design traceability table (design §17.1) and
directly validates Requirement 14.5 and Requirement 10.3.

Strategy summary
----------------
* ``symbol_strategy`` — a small fixed universe of realistic NSE tickers
  (RELIANCE, TCS, INFY, HDFCBANK, ITC). The round-trip is independent
  of symbol value, so a handful of examples is sufficient to exercise
  the field; a larger universe just slows the test without improving
  coverage.
* ``canonical_text_strategy`` — alphabetic + space + newline text,
  10–2000 chars. We deliberately restrict the alphabet to ASCII letters
  and whitespace so generated bodies cannot accidentally contain:

  - ``<!-- … -->`` comment syntax (could clash with the format's own
    meta / section markers).
  - Markdown heading or table delimiters (not what this test exercises).
  - Unicode characters outside the BMP (safe, but unnecessary and
    increases shrink noise).

  The parser is tested against richer inputs by the unit tests in
  ``test_parser_canonical.py`` (unit layer); this property test is
  scoped to the *structural* round-trip.
* ``sections_strategy`` — picks 0–3 non-overlapping spans with distinct
  ``snake_case`` names from a fixed list. Offsets are drawn against the
  actual canonical-text length so every generated document is
  construction-valid against the :class:`CanonicalDoc` validator (which
  rejects out-of-range, overlapping, or duplicate-named spans).
* ``doc_strategy`` — stitches the above together, plus a deterministic
  UUID, a 64-char lowercase-hex sha256, a bounded metadata dict, and a
  UTC-aware ``published_at``.

Hypothesis configuration
------------------------
``max_examples=50`` covers plenty of structural variation without
blowing out CI wall-time, ``deadline=None`` stops Hypothesis from
flaking on cold-start JSON / regex overhead, and
``suppress_health_check=[HealthCheck.data_too_large]`` lets the 2000-char
upper bound on generated bodies through without the default data-size
alarm firing (the bound is a deliberate choice, not noise).
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.research.ingest.parser.canonical import (
    CanonicalDoc,
    SectionSpan,
    _normalise_for_equality,
    parse_canonical,
    pretty_print,
)


# --------------------------------------------------------------------------- #
# Fixed universes                                                             #
# --------------------------------------------------------------------------- #


# A small, realistic ticker universe. The round-trip property is
# symbol-independent, so we keep this list short to minimise example
# noise during Hypothesis shrinking.
_SYMBOLS: tuple[str, ...] = (
    "RELIANCE",
    "TCS",
    "INFY",
    "HDFCBANK",
    "ITC",
)

# Document type literal set matches the DocumentType alias in
# ``canonical.py``; keeping it in sync by copy is cheap and avoids
# importing a Literal at runtime.
_DOCUMENT_TYPES: tuple[str, ...] = (
    "announcement",
    "annual_report",
    "concall",
    "shareholding",
    "ir_deck",
    "user_upload",
)

# Fixed pool of well-formed snake_case section names. The
# ``CanonicalDoc`` validator requires names to match
# ``[a-z][a-z0-9_]*`` and to be unique within a document; by drawing
# from this fixed list of length 4 we can cleanly generate 0–3 distinct
# names without a rejection sampler.
_SECTION_NAMES: tuple[str, ...] = (
    "management_commentary",
    "numerical_results",
    "shareholding",
    "auditor_report",
)

# Restricted alphabet — ASCII letters + space + newline. See the module
# docstring for why we exclude punctuation, unicode, and HTML-comment
# syntax. This alphabet still exercises every interesting code path in
# the printer + parser pair.
_TEXT_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz \n"


# --------------------------------------------------------------------------- #
# Hypothesis strategies                                                       #
# --------------------------------------------------------------------------- #


symbol_strategy = st.sampled_from(_SYMBOLS)
"""Draws a ticker symbol from a small, realistic NSE universe."""


document_type_strategy = st.sampled_from(_DOCUMENT_TYPES)
"""Draws one of the six ``DocumentType`` literal values."""


canonical_text_strategy = st.text(
    alphabet=_TEXT_ALPHABET,
    min_size=10,
    max_size=2000,
)
"""Draws a canonical-text body in the restricted alphabet.

Size range is 10–2000 chars: the lower bound guarantees we always have
room for at least one reasonable section span, and the upper bound keeps
Hypothesis shrinking fast while still exercising the multi-kilobyte
path the real pipeline sees.
"""


def _hex_sha256_from(seed: str) -> str:
    """Deterministic lowercase-hex SHA-256 from an arbitrary seed string.

    The :class:`CanonicalDoc` validator enforces a 64-char lowercase
    hex string on ``sha256`` (see ``_sha256_is_hex``), so we cannot
    simply draw 64 hex characters via Hypothesis without a custom
    strategy. Hashing an arbitrary seed is the simplest way to
    guarantee validator compliance while still giving Hypothesis
    deterministic shrinking behaviour (identical seeds always yield
    identical hashes, so shrunk examples do not bounce between
    different sha256 values).
    """
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


@st.composite
def sections_strategy(
    draw: st.DrawFn, canonical_text: str
) -> list[SectionSpan]:
    """Draw 0–3 non-overlapping sections with distinct names.

    The strategy:

    1. Picks a section count ``n`` in ``[0, 3]``. Counts above 3 would
       need more distinct section names than we have in the fixed
       pool; 3 is enough to exercise the ordering + overlap checks in
       the :class:`CanonicalDoc` validator.
    2. Partitions ``range(0, len(canonical_text))`` into ``n`` disjoint
       ``[start, end)`` spans by drawing ``2 * n`` distinct offsets
       and sorting them. This guarantees non-overlap by construction,
       which is the only way to generate a valid list without a
       rejection loop on the validator.
    3. Assigns a unique name to each span by sampling ``n`` distinct
       names from the fixed pool.

    When ``canonical_text`` is shorter than ``2 * n`` characters we
    fall back to ``n = 0``; the round-trip property holds trivially for
    zero-section documents and exercising that case is part of the
    required coverage anyway.
    """
    max_sections = min(3, len(canonical_text) // 2)
    if max_sections <= 0:
        return []

    n = draw(st.integers(min_value=0, max_value=max_sections))
    if n == 0:
        return []

    # Draw 2*n distinct offsets in [0, len(text)] — these become the
    # paired (start, end) boundaries after sorting.
    boundaries = draw(
        st.lists(
            st.integers(min_value=0, max_value=len(canonical_text)),
            min_size=2 * n,
            max_size=2 * n,
            unique=True,
        )
    )
    boundaries.sort()

    # Draw n distinct section names. We sample from the fixed pool
    # without replacement to guarantee uniqueness; the validator
    # rejects duplicates.
    names = draw(
        st.lists(
            st.sampled_from(_SECTION_NAMES),
            min_size=n,
            max_size=n,
            unique=True,
        )
    )

    spans: list[SectionSpan] = []
    for i, name in enumerate(names):
        start = boundaries[2 * i]
        end = boundaries[2 * i + 1]
        # Post-sort, start <= end is guaranteed. start == end is
        # allowed by the CanonicalDoc validator (end >= start) and is
        # an interesting edge case to exercise (zero-length section).
        spans.append(SectionSpan(name=name, start=start, end=end))

    return spans


@st.composite
def metadata_strategy(draw: st.DrawFn) -> dict[str, Any]:
    """Draw a small, JSON-serialisable metadata dict.

    Values are drawn from a tight pool (int, bool, short ASCII string,
    None) to keep shrinking fast and to avoid generating shapes that
    the JSON encoder would choke on. The pretty-printer serialises
    metadata via :func:`json.dumps` with ``sort_keys=True``, so
    generating any JSON-serialisable dict is sufficient to exercise
    the round-trip path.
    """
    n = draw(st.integers(min_value=0, max_value=3))
    result: dict[str, Any] = {}
    for _ in range(n):
        key = draw(
            st.text(
                alphabet="abcdefghijklmnopqrstuvwxyz_",
                min_size=1,
                max_size=12,
            )
        )
        value = draw(
            st.one_of(
                st.integers(min_value=-10_000, max_value=10_000),
                st.booleans(),
                st.text(alphabet=_TEXT_ALPHABET, min_size=0, max_size=30),
                st.none(),
            )
        )
        result[key] = value
    return result


@st.composite
def doc_strategy(draw: st.DrawFn) -> CanonicalDoc:
    """Draw a construction-valid :class:`CanonicalDoc` for the round trip.

    Combines the primitive strategies above. ``document_id`` is drawn
    as a fresh UUID per example — the round-trip serialises it through
    the meta block as a plain UUID string, so any valid UUID exercises
    the path.

    ``sha256`` is derived deterministically from the canonical text so
    shrunk examples have stable sha256 values (Hypothesis's delta
    debugger prefers stable invariants) while still satisfying the
    64-char lowercase-hex validator on :class:`CanonicalDoc.sha256`.

    ``published_at`` is a UTC-aware datetime drawn in a bounded range
    (2000-01-01 to 2050-12-31) so we stay inside the representable-
    timestamp window on every platform and the isoformat() ↔
    fromisoformat() pair round-trips losslessly.
    """
    canonical_text = draw(canonical_text_strategy)
    return CanonicalDoc(
        document_id=uuid4(),
        symbol=draw(symbol_strategy),
        document_type=draw(document_type_strategy),
        source_url=draw(
            st.one_of(
                st.none(),
                st.text(
                    alphabet="abcdefghijklmnopqrstuvwxyz0123456789./:-_",
                    min_size=10,
                    max_size=80,
                ),
            )
        ),
        sha256=_hex_sha256_from(canonical_text),
        published_at=draw(
            st.datetimes(
                min_value=datetime(2000, 1, 1),
                max_value=datetime(2050, 12, 31),
                timezones=st.just(timezone.utc),
            )
        ),
        canonical_text=canonical_text,
        sections=draw(sections_strategy(canonical_text)),
        metadata=draw(metadata_strategy()),
    )


# --------------------------------------------------------------------------- #
# The property test                                                           #
# --------------------------------------------------------------------------- #


@given(doc=doc_strategy())
@settings(
    max_examples=50,
    deadline=None,
    # The 2000-char body upper bound is a deliberate choice — see the
    # module docstring for why — and Hypothesis's default data-size
    # budget would otherwise fire a HealthCheck.data_too_large alert
    # for no correctness reason.
    suppress_health_check=[HealthCheck.data_too_large],
)
def test_canonical_doc_roundtrip(doc: CanonicalDoc) -> None:
    """``parse_canonical(pretty_print(doc)) ≡ doc`` modulo whitespace.

    Validates: Requirements 14.5, 10.3.

    The equivalence has two legs, each asserted independently so the
    failure message points to the right field on regression:

    * **Non-text fields** — both sides serialise to the same dict once
      ``canonical_text`` is excluded. This catches every metadata or
      section-span mis-serialisation (missing keys, mangled datetimes,
      reordered spans) with a single structural comparison.
    * **Canonical text** — both sides compare equal after being run
      through :func:`_normalise_for_equality`, the helper defined in
      ``canonical.py`` specifically to codify the whitespace
      normalisations the pretty-printer is permitted to introduce.
      Using the same helper on both sides keeps the property test
      honest: we are not asserting byte equality of
      ``pretty_print(doc).canonical_text`` (which would be trivially
      false because the printer strips / collapses whitespace) — we
      are asserting that every whitespace tweak the printer applies is
      *reversible* under the documented normaliser.
    """
    printed = pretty_print(doc)
    parsed = parse_canonical(printed)

    # Leg 1: every non-text field survives the round trip verbatim.
    # Using model_dump(mode="json") ensures datetimes and UUIDs are
    # compared as their serialised form, matching what actually flows
    # through the meta block.
    assert parsed.model_dump(
        exclude={"canonical_text"}, mode="json"
    ) == doc.model_dump(exclude={"canonical_text"}, mode="json")

    # Leg 2: canonical_text round-trips under the documented
    # whitespace normaliser.
    assert _normalise_for_equality(parsed.canonical_text) == _normalise_for_equality(
        doc.canonical_text
    )
