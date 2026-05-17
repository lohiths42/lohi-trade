"""End-to-end citation-integrity property (design §17.1 Property 1 / Req 14.1).

The retriever-side slice of this invariant lives in Task 6.4
(:mod:`tests.research.test_prop_citation_integrity`) and checks that
``retriever.retrieve()`` never leaks a ``chunk_id`` that is not in the
store. This module covers the *brief* side — the complementary half of
Req 14.1 and Req 3.11: **every citation attached to a brief must
resolve to a real chunk in the active VectorStore under the run's
``(user_id, symbol)`` namespace; every fabricated chunk_id must be
flagged.**

Together the two properties close the loop from design §12 /
design §3.8: the retriever cannot manufacture a chunk_id, and the
citation validator catches the ones a hallucinating synthesizer
might invent after retrieval.

Test architecture
-----------------

For each generated example:

1. Seed a fresh :class:`FakeVectorStore` with ``N`` real
   :class:`ChunkRecord`\\s under ``(user_id, symbol)`` — that is the
   **universe of legitimate chunk_ids**.
2. Build a **brief** whose citations are a mix of:

   * ``K`` ``chunk_id``\\s sampled from the seeded corpus (real), and
   * ``L`` ``chunk_id``\\s that are guaranteed disjoint from the corpus
     (fabricated — the kind of hex-string an LLM might hallucinate).

3. Optionally inject chunks that belong to *another* user or *another*
   symbol (cross-namespace real ids). Those live in the store but do
   not belong to the run's namespace, so the validator must still flag
   them — design §3.8 spells this out and Req 3.10 requires it.

4. Call :func:`validate_citations` and assert three properties:

   * Every fabricated / out-of-namespace ``chunk_id`` appears in the
     violations list.
   * No real, in-namespace ``chunk_id`` appears in the violations list.
   * ``len(violations) == L + (out-of-namespace real ids)`` — exactly
     the fabricated + cross-namespace count, nothing more, nothing less.

Hypothesis configuration
------------------------

``max_examples=60`` per the task spec (the range 50–100 the task
allows). Each example drives real async I/O against the fake store
through the validator's enumeration path, so the per-example cost is
higher than a pure-sync property; the chosen bound keeps full-suite
runtime proportional to the rest of the research tests while still
exploring enough corpus / citation-mix variety to surface regressions.

``deadline=None`` because corpus generation + validator enumeration is
genuinely heavier than the Hypothesis default allows — the same
posture Task 6.4's retriever-side test takes for the same reason.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import UUID

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.research.providers.base import ChunkRecord
from src.research.validators.citation_validator import validate_citations
from src.research.validators.types import UnsupportedClaim
from tests.research.fakes import FakeVectorStore

# --------------------------------------------------------------------------- #
# Fixed universes                                                             #
# --------------------------------------------------------------------------- #
#
# Pinned UUIDs + small symbol set keep Hypothesis shrinks deterministic:
# drawing UUIDs per example makes counter-examples hard to reproduce,
# and collapsing to fixed symbols focuses the search on the
# citation-mix story rather than string entropy.

_RUN_USER_ID: UUID = UUID("11111111-1111-1111-1111-111111111111")
_OTHER_USER_ID: UUID = UUID("22222222-2222-2222-2222-222222222222")
_RUN_SYMBOL: str = "RELIANCE"
_OTHER_SYMBOL: str = "TCS"
_DOCUMENT_ID: UUID = UUID("33333333-3333-3333-3333-333333333333")

# Default ``BAAI/bge-small-en-v1.5`` dim / FakeEmbeddingsProvider dim.
# The validator's :func:`_known_chunk_ids` internal helper probes the
# store for the embedding dim; passing it explicitly skips the probe
# and keeps each example fast.
_DIM: int = 384


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _FakeCitation:
    """Duck-typed citation — only ``.chunk_id`` is read by the validator.

    Mirrors the shape of the full :class:`Citation` Pydantic model the
    brief will carry once Task 13.8 lands, minus fields the citation
    validator does not inspect. Using a ``frozen`` dataclass here
    matches the pattern already in use in
    :mod:`tests.research.test_citation_validator` (Task 11.2's unit
    tests) and guards against accidental in-place mutation during the
    arrange step.
    """

    chunk_id: str


def _build_chunk(
    *,
    chunk_id: str,
    user_id: UUID = _RUN_USER_ID,
    symbol: str = _RUN_SYMBOL,
) -> ChunkRecord:
    """Create a :class:`ChunkRecord` with a harmless non-zero embedding.

    The citation validator never scores relevance — it only reads
    ``chunk_id`` — so the embedding values are irrelevant to the
    outcome. We still give every chunk a non-zero first component so
    the :class:`FakeVectorStore`'s cosine path (zero-norm guard) does
    not short-circuit during the validator's internal enumeration —
    mirroring the shape production adapters actually return.
    """
    emb = [0.0] * _DIM
    emb[0] = 1.0
    return ChunkRecord(
        chunk_id=chunk_id,
        document_id=_DOCUMENT_ID,
        user_id=user_id,
        symbol=symbol,
        position=0,
        token_count=1,
        text=f"text for {chunk_id}",
        embedding=emb,
        embedding_model="fake",
        embedding_dim=_DIM,
    )


def _run(coro):
    """Drive an async coroutine inside a sync Hypothesis test body.

    Matches the ``asyncio.run`` pattern used by
    :mod:`tests.research.test_citation_validator` and
    :mod:`tests.research.test_prop_citation_integrity` so the fake
    store's internal state is isolated per example.
    """
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# Strategies                                                                  #
# --------------------------------------------------------------------------- #


# ``chunk_id`` alphabet: ASCII lower hex + dash. Restricted so (a)
# generated ids look like real SHA-256 fragments, and (b) Hypothesis
# shrinks produce readable counter-examples when a regression fires.
_ID_ALPHABET = "0123456789abcdef-"


def _chunk_id_text(min_size: int, max_size: int) -> st.SearchStrategy[str]:
    """Hex-ish id strategy, non-empty, deduplicable via a ``filter``."""
    return st.text(
        alphabet=_ID_ALPHABET,
        min_size=min_size,
        max_size=max_size,
    ).filter(lambda s: s.strip() != "")


@st.composite
def _citation_mix(
    draw: st.DrawFn,
) -> tuple[
    list[ChunkRecord],  # corpus seeded under the run namespace
    list[ChunkRecord],  # extra chunks under other user/symbol
    list[_FakeCitation],  # brief citations, mixed real + fake
    set[str],  # every chunk_id expected to VIOLATE
    set[str],  # every chunk_id expected to PASS
]:
    """Draw a (corpus, brief) pair plus the expected violation partition.

    Output shape mirrors the property's assertion structure: the test
    body only needs to set-compare the validator's violation list
    against the two pre-computed id sets, which keeps the assertions
    short and each failure message focused.

    Drawing details
    ---------------

    * The **real corpus** is always non-empty (``N ≥ 1``) so the
      "sampled real id" case is exercised. The upper bound
      (``N ≤ 12``) keeps the store's internal enumeration cost per
      example bounded.
    * The **fabricated ids** are generated fresh and post-filtered to
      be disjoint from the real ids — a collision would turn a
      "should violate" into a "should pass" and silently weaken the
      property.
    * Optional **cross-namespace** chunks (other ``user_id`` /
      ``symbol``) are seeded into the store with ids that *do* exist
      in the store but *should not* resolve for the run's namespace.
      Req 3.10 + design §3.8 require these to be flagged too.
    * The **brief ordering** is interleaved — real and fake citations
      are shuffled together via a draw-time permutation — so a
      validator that relied on any ordering assumption surfaces as a
      shrink-minimal counter-example.
    """
    # 1. Real corpus under the run's (user_id, symbol).
    n_real = draw(st.integers(min_value=1, max_value=12))
    real_ids: list[str] = []
    seen: set[str] = set()
    for _ in range(n_real):
        candidate = draw(_chunk_id_text(min_size=4, max_size=16))
        # Reject duplicates against the growing real-ids set so each
        # real chunk is distinct (upsert would otherwise coalesce them
        # via the idempotence contract and shrink the effective
        # namespace size below ``n_real``).
        while candidate in seen:
            candidate = draw(_chunk_id_text(min_size=4, max_size=16))
        seen.add(candidate)
        real_ids.append(candidate)
    real_corpus = [_build_chunk(chunk_id=cid) for cid in real_ids]

    # 2. Fabricated ids — guaranteed disjoint from ``real_ids``. The
    # filter is bounded because ``_ID_ALPHABET`` is 17 chars wide, so
    # collision probability at length 4+ is negligible even at the
    # minimum size.
    n_fake = draw(st.integers(min_value=0, max_value=6))
    fake_ids: list[str] = []
    for _ in range(n_fake):
        candidate = draw(_chunk_id_text(min_size=4, max_size=16))
        while candidate in seen:
            candidate = draw(_chunk_id_text(min_size=4, max_size=16))
        seen.add(candidate)
        fake_ids.append(candidate)

    # 3. Cross-namespace chunks — live in the store, but under a
    # different user_id or a different symbol. Their ids should
    # violate for the run's namespace (Req 3.10, design §3.8).
    n_cross = draw(st.integers(min_value=0, max_value=4))
    cross_chunks: list[ChunkRecord] = []
    cross_ids: list[str] = []
    for _ in range(n_cross):
        candidate = draw(_chunk_id_text(min_size=4, max_size=16))
        while candidate in seen:
            candidate = draw(_chunk_id_text(min_size=4, max_size=16))
        seen.add(candidate)
        # Randomly choose which namespace axis is violated — other
        # user, other symbol, or both — so the property exercises
        # every dimension of Req 3.10.
        axis = draw(st.sampled_from(["user", "symbol", "both"]))
        user_id = _OTHER_USER_ID if axis in ("user", "both") else _RUN_USER_ID
        symbol = _OTHER_SYMBOL if axis in ("symbol", "both") else _RUN_SYMBOL
        cross_chunks.append(
            _build_chunk(chunk_id=candidate, user_id=user_id, symbol=symbol),
        )
        cross_ids.append(candidate)

    # 4. Build the brief: pick some subset of real ids to actually
    # cite (``k_real ≤ n_real``; duplicate draws allowed so a real id
    # may appear more than once in the brief, which must still pass),
    # concatenate fake + cross ids (every one cited exactly once so
    # the violation count is exactly predictable), and shuffle.
    k_real = draw(st.integers(min_value=0, max_value=n_real))
    cited_real_ids: list[str] = (
        draw(
            st.lists(
                st.sampled_from(real_ids),
                min_size=k_real,
                max_size=k_real,
            ),
        )
        if k_real > 0
        else []
    )

    cited = (
        [_FakeCitation(chunk_id=cid) for cid in cited_real_ids]
        + [_FakeCitation(chunk_id=cid) for cid in fake_ids]
        + [_FakeCitation(chunk_id=cid) for cid in cross_ids]
    )
    # Draw a permutation so the shuffled order is reproducible under
    # shrinking — ``st.permutations`` yields a concrete list Hypothesis
    # can minimise, unlike ``random.shuffle`` which would introduce
    # non-reproducibility into the property.
    brief = draw(st.permutations(cited))

    expected_violation_ids = set(fake_ids) | set(cross_ids)
    expected_pass_ids = set(cited_real_ids)
    return real_corpus, cross_chunks, brief, expected_violation_ids, expected_pass_ids


# --------------------------------------------------------------------------- #
# Property                                                                    #
# --------------------------------------------------------------------------- #


@given(_citation_mix())
@settings(
    max_examples=60,
    deadline=None,
    suppress_health_check=[
        # Corpus draws plus cross-namespace chunks + brief permutation
        # push per-example data generation above Hypothesis's default;
        # this is expected, not a bug to fix.
        HealthCheck.data_too_large,
        HealthCheck.too_slow,
    ],
)
def test_citation_validator_flags_every_fake_and_no_real(
    drawn: tuple[
        list[ChunkRecord],
        list[ChunkRecord],
        list[_FakeCitation],
        set[str],
        set[str],
    ],
) -> None:
    """End-to-end citation integrity against a real ``VectorStore``.

    Validates: Requirements 14.1, 3.11, 3.10.

    Given a brief whose citations are a mix of real in-namespace ids,
    fabricated ids, and real-but-out-of-namespace ids, the validator
    must:

    1. Flag **every** fabricated id (``reason="citation_mismatch"``),
    2. Flag **every** cross-namespace id (same reason — Req 3.10
       requires user_id + symbol scoping),
    3. Flag **no** real in-namespace id,
    4. Emit exactly ``|fake ∪ cross|`` violations — no more, no less.

    End-to-end flow per example:

    * Seed a fresh :class:`FakeVectorStore` with the run-namespace
      corpus plus any cross-namespace chunks.
    * Call :func:`validate_citations` — the module-level async helper
      the Orchestrator uses in production (design §3.5, §12).
    * Partition the returned :class:`UnsupportedClaim`\\s by
      ``claim_text`` (which carries the offending ``chunk_id``) and
      assert against the expected partitions produced at generation
      time.
    """
    real_corpus, cross_chunks, brief, expected_violation_ids, expected_pass_ids = drawn

    async def _body() -> None:
        store = FakeVectorStore()
        # Seed the run-namespace corpus first so its enumeration is
        # deterministic, then layer in cross-namespace chunks (which
        # must NOT be reachable via the run's (user_id, symbol)
        # filter — this is precisely the invariant being tested).
        await store.upsert(real_corpus)
        if cross_chunks:
            await store.upsert(cross_chunks)

        violations = await validate_citations(
            vector_store=store,
            brief=brief,
            user_id=_RUN_USER_ID,
            symbol=_RUN_SYMBOL,
            embedding_dim=_DIM,
        )

        # Every violation is the canonical citation_mismatch claim
        # shape — a different reason would mean the validator is
        # misclassifying, which is a Req 14.1 regression.
        for v in violations:
            assert isinstance(
                v, UnsupportedClaim
            ), f"expected UnsupportedClaim, got {type(v).__name__}"
            assert v.reason == "citation_mismatch", (
                f"violation {v.claim_text!r} has reason {v.reason!r}; "
                f"expected 'citation_mismatch'"
            )

        violated_ids = {v.claim_text for v in violations}

        # --- Main property: every fabricated / cross-namespace id is --
        # flagged. A miss here means the validator let a hallucinated
        # chunk_id through — the exact failure mode design §12 exists
        # to prevent.
        missing = expected_violation_ids - violated_ids
        assert not missing, (
            f"validator failed to flag fabricated/out-of-namespace ids: "
            f"{sorted(missing)}; violated={sorted(violated_ids)}"
        )

        # --- Main property: no real in-namespace id is flagged. ------
        # A false positive here would reject a legitimate citation and
        # trigger spurious re-synthesis loops in production.
        false_positives = expected_pass_ids & violated_ids
        assert not false_positives, (
            f"validator flagged real in-namespace ids as mismatches: " f"{sorted(false_positives)}"
        )

        # --- Exact violation count -----------------------------------
        # A count mismatch means the validator either duplicated a
        # violation (e.g. by failing to de-dupe internally) or dropped
        # one silently. The brief's fake + cross lists are constructed
        # to have each id appear exactly once, so the expected count
        # is deterministic.
        assert len(violations) == len(expected_violation_ids), (
            f"expected {len(expected_violation_ids)} violations "
            f"({sorted(expected_violation_ids)}); "
            f"got {len(violations)} ({sorted(violated_ids)})"
        )

    _run(_body())


# --------------------------------------------------------------------------- #
# Regression anchors                                                          #
# --------------------------------------------------------------------------- #


def test_all_real_citations_produce_no_violations() -> None:
    """A brief citing only real in-namespace ids passes cleanly.

    Validates: Requirement 14.1 (trivial direction — a clean brief
    must not be rejected).

    Kept as a non-Hypothesis anchor so a validator regression that
    shrinks to "every citation is flagged" cannot hide behind the
    empty-corpus edge cases the property strategy happens to minimise
    toward.
    """

    async def _body() -> None:
        store = FakeVectorStore()
        await store.upsert(
            [_build_chunk(chunk_id=f"real-{i}") for i in range(5)],
        )
        brief = [_FakeCitation(chunk_id=f"real-{i}") for i in range(5)]
        violations = await validate_citations(
            vector_store=store,
            brief=brief,
            user_id=_RUN_USER_ID,
            symbol=_RUN_SYMBOL,
            embedding_dim=_DIM,
        )
        assert violations == [], f"expected no violations for all-real brief, got {violations!r}"

    asyncio.run(_body())


def test_all_fake_citations_are_all_flagged() -> None:
    """A brief citing only fabricated ids has every citation flagged.

    Validates: Requirement 14.1 (the anchor direction of the property
    — 100% fabricated ⇒ 100% violations).
    """

    async def _body() -> None:
        store = FakeVectorStore()
        await store.upsert([_build_chunk(chunk_id="real-a")])
        brief = [_FakeCitation(chunk_id=f"ghost-{i}") for i in range(7)]
        violations = await validate_citations(
            vector_store=store,
            brief=brief,
            user_id=_RUN_USER_ID,
            symbol=_RUN_SYMBOL,
            embedding_dim=_DIM,
        )
        assert len(violations) == 7, f"expected 7 violations (all ghosts), got {len(violations)}"
        assert {v.claim_text for v in violations} == {f"ghost-{i}" for i in range(7)}
        assert all(v.reason == "citation_mismatch" for v in violations)

    asyncio.run(_body())


def test_cross_user_real_chunk_is_flagged() -> None:
    """A real chunk owned by a *different* user does not resolve.

    Validates: Requirement 14.1 and Requirement 3.10 — the validator
    must scope by ``user_id`` even when the ``chunk_id`` is real.
    Anchored as a standalone test so a regression in the namespace
    scoping path has a binary, non-randomised failure signal.
    """

    async def _body() -> None:
        store = FakeVectorStore()
        # Seed a chunk with the *same* chunk_id under the OTHER user.
        # The run's filter pins ``_RUN_USER_ID`` so the id must not
        # resolve even though it physically exists in the store.
        await store.upsert(
            [_build_chunk(chunk_id="shared-id", user_id=_OTHER_USER_ID)],
        )
        violations = await validate_citations(
            vector_store=store,
            brief=[_FakeCitation(chunk_id="shared-id")],
            user_id=_RUN_USER_ID,
            symbol=_RUN_SYMBOL,
            embedding_dim=_DIM,
        )
        assert len(violations) == 1
        assert violations[0].reason == "citation_mismatch"
        assert violations[0].claim_text == "shared-id"

    asyncio.run(_body())


def test_cross_symbol_real_chunk_is_flagged() -> None:
    """A real chunk under a *different* symbol does not resolve either.

    Validates: Requirement 14.1 and Requirement 3.10 — the run's
    ``symbol`` filter must narrow just as strictly as its ``user_id``.
    """

    async def _body() -> None:
        store = FakeVectorStore()
        await store.upsert(
            [_build_chunk(chunk_id="other-symbol-chunk", symbol=_OTHER_SYMBOL)],
        )
        violations = await validate_citations(
            vector_store=store,
            brief=[_FakeCitation(chunk_id="other-symbol-chunk")],
            user_id=_RUN_USER_ID,
            symbol=_RUN_SYMBOL,
            embedding_dim=_DIM,
        )
        assert len(violations) == 1
        assert violations[0].reason == "citation_mismatch"
        assert violations[0].claim_text == "other-symbol-chunk"

    asyncio.run(_body())


if __name__ == "__main__":  # pragma: no cover
    # Allow ``python tests/research/test_prop_citation_integrity_e2e.py``
    # for quick local iteration during development.
    pytest.main([__file__, "-v"])
