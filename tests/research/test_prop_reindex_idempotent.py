"""Idempotent re-indexing — design §17.1 Property 4 / Req 14.4, Req 3.12.

The invariant under test: **chunking the same canonical document with
the same ``chunker_version`` produces an identical set of ``chunk_id``s
every time.** This is the enabling property behind Req 3.12 — "THE
Lohi_Research SHALL provide a re-index operation that, for a given
symbol, re-parses and re-embeds all documents and SHALL produce the same
set of chunk_ids (idempotent re-indexing at the chunk-id level for
unchanged source content)."

Two complementary properties are exercised here, both of which must
hold for the :meth:`VectorStore.upsert` contract to be a *true* upsert:

1. **Stability** — :func:`~src.research.ingest.chunker.chunk_document`
   is deterministic: two calls with the same ``CanonicalDoc`` and same
   kwargs yield the same set of ``chunk_id``s.
2. **Version sensitivity** — bumping ``chunker_version`` produces a
   *different* set of ``chunk_id``s. This protects the system from
   silent chunking-algorithm drift: a change to the splitter that does
   not come with a version bump would collide with existing
   ``chunk_id``s and silently corrupt retrieval. The test forces
   ``v1`` vs ``v2`` to be disjoint.

A third sanity check (``test_chunk_ids_are_sha256_hex``) asserts the
derived IDs actually look like the design's specified formula —
``sha256(document_sha256 || chunker_version || position)``, which
yields 64-char lowercase hex. This catches regressions in the hash
function itself (e.g. an accidental switch to SHA-1 or MD5).

Strategy summary
----------------
* ``canonical_text_strategy`` — an ASCII-letter + space + newline body
  with a size range (100, 5000) chars that guarantees the default
  chunker (800-token / 3200-char window) emits **multiple** chunks.
  A single-chunk document would still satisfy the stability property
  trivially but would not exercise the multi-position chunk-id path,
  which is the interesting case for Req 3.12.
* ``doc_strategy`` — a construction-valid :class:`CanonicalDoc` built
  around the generated text. ``sha256`` is derived deterministically
  from the body so shrunk examples have stable hashes.

Hypothesis configuration
------------------------
``max_examples=50`` covers plenty of structural variation without
blowing out CI wall-time, ``deadline=None`` stops Hypothesis from
flaking on cold-start SHA-256 / recursion overhead, and
``suppress_health_check=[HealthCheck.data_too_large]`` lets the 5000-char
upper bound on generated bodies through without the default data-size
alarm firing.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from uuid import uuid4

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.research.ingest.chunker import chunk_document
from src.research.ingest.parser.canonical import CanonicalDoc


# --------------------------------------------------------------------------- #
# Fixed universes (kept in sync with test_prop_parser_roundtrip.py)           #
# --------------------------------------------------------------------------- #


_SYMBOLS: tuple[str, ...] = ("RELIANCE", "TCS", "INFY", "HDFCBANK", "ITC")

_DOCUMENT_TYPES: tuple[str, ...] = (
    "announcement",
    "annual_report",
    "concall",
    "shareholding",
    "ir_deck",
    "user_upload",
)

# Restricted alphabet — keeps generated text compatible with the
# canonical-doc format (no embedded HTML comments, no delimiter
# collisions) and makes Hypothesis shrinks readable.
_TEXT_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz \n"

# 64-char lowercase hex regex, matching the shape validated by
# ``CanonicalDoc.sha256`` (``_SHA256_HEX_RE`` in ``canonical.py``).
# The derived ``chunk_id`` inherits that same shape via the
# ``sha256(document_sha256 || chunker_version || position)`` formula.
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


# --------------------------------------------------------------------------- #
# Strategies                                                                  #
# --------------------------------------------------------------------------- #


# Minimum body length of 100 chars guarantees the chunker emits at
# least one record; 5000 chars (≈1250 tokens) exceeds the default
# 800-token window so most generated docs produce multiple chunks,
# which is the interesting case for the set-equality property.
canonical_text_strategy = st.text(
    alphabet=_TEXT_ALPHABET,
    min_size=100,
    max_size=5000,
)


def _hex_sha256_from(seed: str) -> str:
    """Deterministic lowercase-hex SHA-256 from an arbitrary seed string.

    See :func:`tests.research.test_prop_parser_roundtrip._hex_sha256_from`
    for the rationale — identical seeds yield identical hashes, so
    shrunk examples have stable ``sha256`` values.
    """
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


@st.composite
def doc_strategy(draw: st.DrawFn) -> CanonicalDoc:
    """Draw a construction-valid :class:`CanonicalDoc` for chunker tests.

    Deliberately leaves ``sections`` empty: the chunker only consumes
    ``canonical_text`` + ``sha256``, so section spans are irrelevant to
    the idempotence property and generating them would just slow the
    test down.
    """
    canonical_text = draw(canonical_text_strategy)
    return CanonicalDoc(
        document_id=uuid4(),
        symbol=draw(st.sampled_from(_SYMBOLS)),
        document_type=draw(st.sampled_from(_DOCUMENT_TYPES)),
        source_url=None,
        sha256=_hex_sha256_from(canonical_text),
        published_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        canonical_text=canonical_text,
        sections=[],
        metadata={},
    )


# --------------------------------------------------------------------------- #
# Property tests                                                              #
# --------------------------------------------------------------------------- #


@given(doc=doc_strategy())
@settings(
    max_examples=50,
    deadline=None,
    # 5000-char bodies are our deliberate upper bound; suppress the
    # default data-size alert so Hypothesis does not flag the choice
    # as too-much-entropy.
    suppress_health_check=[HealthCheck.data_too_large],
)
def test_chunking_is_idempotent(doc: CanonicalDoc) -> None:
    """Two invocations with identical inputs yield identical ``chunk_id`` sets.

    Validates: Requirements 14.4, 3.12.

    The test calls :func:`chunk_document` twice on the same
    :class:`CanonicalDoc` with the same kwargs and compares the
    resulting sets of ``chunk_id``s. Set equality — not list equality —
    is what Req 3.12 actually guarantees ("SHALL produce the same set
    of chunk_ids"), so that is what we assert.

    We also assert the count matches: a drift in chunk count would
    still satisfy set equality if the extra chunks happened to reuse
    existing IDs, which is a failure mode worth catching directly.
    """
    user_id = uuid4()

    first = chunk_document(doc, user_id=user_id)
    second = chunk_document(doc, user_id=user_id)

    # Count must match: dropping or adding a chunk on the second call
    # is a bug even if the retained IDs happen to be identical.
    assert len(first) == len(second), (
        f"chunk count drift: first={len(first)}, second={len(second)}"
    )

    # Set equality is the formal Req 3.12 guarantee.
    assert {c.chunk_id for c in first} == {c.chunk_id for c in second}

    # List equality is the stronger guarantee that falls out of the
    # chunker being pure + deterministic. Assert it too so a future
    # regression that keeps the set stable but shuffles the order
    # (e.g. a non-deterministic walk through a dict) fails loudly.
    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]


@given(doc=doc_strategy())
@settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.data_too_large],
)
def test_chunker_version_bump_changes_ids(doc: CanonicalDoc) -> None:
    """Bumping ``chunker_version`` yields a disjoint ``chunk_id`` set.

    Validates: Requirements 14.4, 3.12.

    A silent chunker-algorithm change (without a version bump) would
    collide with existing ``chunk_id``s and corrupt retrieval: the old
    embedding would still be indexed under an ID that now points at
    different text. This test locks that down by asserting the v1 set
    and v2 set are **disjoint** on any non-trivial document.

    ``chunk_id = sha256(document_sha256 || chunker_version || position)``
    makes disjointness follow from SHA-256's collision resistance: the
    chunker_version bytes differ, so every derived hash differs with
    overwhelming probability. A failure here would be a real bug —
    either the chunker is ignoring the ``chunker_version`` kwarg or
    its hash derivation has been changed in a way that drops the
    version contribution.
    """
    user_id = uuid4()

    v1_chunks = chunk_document(doc, user_id=user_id, chunker_version="v1")
    v2_chunks = chunk_document(doc, user_id=user_id, chunker_version="v2")

    # Count must match — the version bump affects only the id
    # derivation, not the text splitter, so the number of emitted
    # chunks is identical between v1 and v2.
    assert len(v1_chunks) == len(v2_chunks)

    v1_ids = {c.chunk_id for c in v1_chunks}
    v2_ids = {c.chunk_id for c in v2_chunks}

    # The two sets must be disjoint. We only run the assertion when
    # the document actually produced chunks; a zero-chunk doc (not
    # possible here given min_size=100, but guarded anyway) would
    # make both sets empty and disjointness would be vacuous.
    if v1_ids:
        assert v1_ids.isdisjoint(v2_ids), (
            "v1 and v2 chunk IDs overlap — chunker_version is not "
            "being mixed into the chunk_id hash"
        )


@given(doc=doc_strategy())
@settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.data_too_large],
)
def test_chunk_ids_are_sha256_hex(doc: CanonicalDoc) -> None:
    """Every emitted ``chunk_id`` is a 64-char lowercase hex string.

    Validates: Requirement 3.12.

    Design §3.3 specifies the formula ``chunk_id = sha256(document_sha256
    || chunker_version || position)``. SHA-256's hexdigest is a 64-char
    lowercase hex string — any other shape (shorter, uppercase, base64)
    means the derivation function has drifted away from the contract
    and a downstream audit or a cross-repository migration would break.

    Kept as a separate test so a regression in the hash shape fails with
    a pointed message rather than being smeared across the set-equality
    checks above.
    """
    user_id = uuid4()
    chunks = chunk_document(doc, user_id=user_id)

    for chunk in chunks:
        assert _HEX64_RE.fullmatch(chunk.chunk_id), (
            f"chunk_id {chunk.chunk_id!r} is not 64 lowercase hex chars"
        )
