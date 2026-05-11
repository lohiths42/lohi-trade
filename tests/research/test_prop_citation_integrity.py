"""Citation integrity — design §17.1 Property 1 / Req 14.1, Req 3.11.

The invariant under test: **every chunk the retriever returns is a
chunk the vector store actually has.** Req 3.11 frames this from the
brief side — "every Citation SHALL resolve to an existing chunk in the
Vector_Store at the time of generation" — and Req 14.1 formalises it
as a property test that must pass in CI.

At this point in the build (Task 6.4) the :class:`Citation` type does
not exist yet — it lands in the validators layer in Phase 11. The task
description carves out the retriever-side slice of the property:
"every ``ChunkHit.chunk.chunk_id`` returned by ``retriever.retrieve()``
exists in the vector store's underlying chunk list". That is the
foundational guarantee the validator layer will later build on top of —
if the retriever leaks a non-existent chunk_id, no amount of
validator-side checking can recover.

Strategy sketch
---------------

* Build a corpus of :class:`ChunkRecord`\\s with Hypothesis, seed it
  into a :class:`~tests.research.fakes.vector_store.FakeVectorStore`
  via ``upsert``.
* Construct a :class:`~src.research.index.retriever.HybridRetriever`
  with :class:`~tests.research.fakes.embeddings.FakeEmbeddingsProvider`
  and ``bm25_index=None`` (dense-only, as the task prescribes).
* Draw a query string that may or may not overlap with any chunk text.
* Call ``retrieve(query, filter=RetrievalFilter(user_id=...), k=k)``.
* Assert every returned hit's ``chunk_id`` is in the set of upserted
  IDs.

Two reinforcing invariants are checked alongside the main property,
because they catch distinct regression modes:

1. **Namespace containment** — every returned chunk's ``user_id``
   matches the filter's ``user_id``. A retriever that filters correctly
   at the store level but mutates records post-fetch would pass the
   "chunk_id exists" check while silently leaking cross-tenant content.
2. **Size bound** — the result length never exceeds ``k``. A fusion bug
   that accidentally deduplicated lossily could return more than ``k``
   hits even if all of them are valid.

Why dense-only
--------------
The task explicitly specifies ``bm25_index=None``. Dense-only keeps the
property test focused on the vector-store + retriever interaction;
Task 6.1's BM25 path is exercised separately by its own unit tests (the
BM25Index class is pure-Python and dependency-free so it does not need
Hypothesis-driven coverage to ship).

Hypothesis configuration
------------------------
``max_examples=30`` per the task spec — enough variety in corpus size,
symbol count, and queries to surface regressions without bloating CI
wall-time. ``deadline=None`` because the fake providers allocate a
384-dim vector per chunk and that can exceed the Hypothesis default on
the larger generated corpora.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.research.index.retriever import HybridRetriever
from src.research.providers.base import ChunkRecord, RetrievalFilter
from tests.research.fakes import FakeEmbeddingsProvider, FakeVectorStore

# --------------------------------------------------------------------------- #
# Fixed universes                                                             #
# --------------------------------------------------------------------------- #
#
# A small, closed set of symbols keeps generated corpora focused on the
# (user_id, symbol) namespacing story without bloating the search
# space. UUIDs are pinned so Hypothesis shrinks are deterministic —
# drawing new UUIDs on every example makes failure counter-examples
# hard to compare across runs.

_SYMBOLS: tuple[str, ...] = ("RELIANCE", "TCS", "INFY", "HDFCBANK", "ITC")

_FIXED_USER_ID: UUID = UUID("11111111-1111-1111-1111-111111111111")
_FIXED_DOCUMENT_ID: UUID = UUID("22222222-2222-2222-2222-222222222222")

# Fake-provider embedding dimension; matches ``FakeEmbeddingsProvider``
# default (384) to keep ``ChunkRecord.embedding_dim`` consistent with
# the embedding lists the fake produces.
_EMBEDDING_DIM: int = 384
_EMBEDDING_MODEL: str = "fake-embeddings"


# --------------------------------------------------------------------------- #
# Strategies                                                                  #
# --------------------------------------------------------------------------- #


# Text alphabet: ASCII letters + space + newline. Restricted so
# tokenisation is stable and Hypothesis shrinks are readable when a
# counter-example fires.
_TEXT_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz \n"


# Chunk body. Min 1 char so ``FakeEmbeddingsProvider`` always has
# material to hash; max 400 so a corpus of 30 chunks stays small
# enough for ``FakeVectorStore``'s O(n) cosine loop.
_chunk_text = st.text(
    alphabet=_TEXT_ALPHABET,
    min_size=1,
    max_size=400,
)


# Query text. Allowed to be empty so we exercise the edge case where
# ``_tokenise`` returns [] — the retriever must still not fabricate
# chunk_ids out of thin air.
_query_text = st.text(
    alphabet=_TEXT_ALPHABET,
    min_size=0,
    max_size=200,
)


async def _embed_one(text: str, dim: int) -> list[float]:
    """Helper: derive the same 384-dim vector ``FakeEmbeddingsProvider`` would.

    Kept async so it can be awaited from inside the strategy without
    spinning up an additional event loop — the strategy runs under
    :func:`asyncio.run` via ``_run`` below.
    """
    provider = FakeEmbeddingsProvider(dim=dim)
    return (await provider.embed([text]))[0]


def _run(coro):  # pragma: no cover - trivial helper
    """Drive an async coroutine to completion inside a sync Hypothesis test.

    Hypothesis does not natively understand ``async def`` test
    functions; the project-standard workaround is to wrap each
    property in a sync shell and :func:`asyncio.run` the body. One
    fresh event loop per example keeps the fakes' internal state
    isolated.
    """
    return asyncio.run(coro)


@st.composite
def _chunk_record(draw: st.DrawFn, *, position: int) -> ChunkRecord:
    """Draw a single :class:`ChunkRecord` compatible with the fake stack.

    ``chunk_id`` is derived from ``position`` + text so distinct
    strategy draws produce distinct ids — a collision would let a
    spurious id-equality assertion pass trivially.
    ``user_id`` is pinned to :data:`_FIXED_USER_ID` so the retriever's
    filter actually matches; Task 7.5 (memory scoping property) will
    drive the cross-user variation separately.
    """
    text = draw(_chunk_text)
    symbol = draw(st.sampled_from(_SYMBOLS))
    # Derive a stable embedding from the text so the chunk_id-vs-
    # embedding pairing survives shrinking. Under the fake provider
    # the embedding is a deterministic function of text.
    embedding = _run(_embed_one(text, _EMBEDDING_DIM))
    # chunk_id includes the position so duplicate-text draws do not
    # collide; the fake store is idempotent by chunk_id (Req 3.12).
    chunk_id = f"c{position:08d}-{hash(text) & 0xFFFF:04x}"
    return ChunkRecord(
        chunk_id=chunk_id,
        document_id=_FIXED_DOCUMENT_ID,
        user_id=_FIXED_USER_ID,
        symbol=symbol,
        position=position,
        token_count=max(1, len(text.split())),
        text=text,
        embedding=embedding,
        embedding_model=_EMBEDDING_MODEL,
        embedding_dim=_EMBEDDING_DIM,
    )


@st.composite
def _corpus(draw: st.DrawFn) -> list[ChunkRecord]:
    """Draw a non-empty corpus of 1..30 ``ChunkRecord``\\s.

    The upper bound keeps each example's end-to-end runtime under ~1s
    on CI hardware (FakeEmbeddingsProvider is deterministic but the
    cosine loop in FakeVectorStore is O(n·dim)).
    """
    n = draw(st.integers(min_value=1, max_value=30))
    return [draw(_chunk_record(position=i)) for i in range(n)]


# --------------------------------------------------------------------------- #
# Property test                                                               #
# --------------------------------------------------------------------------- #


@given(
    corpus=_corpus(),
    query=_query_text,
    k=st.integers(min_value=1, max_value=20),
)
@settings(
    max_examples=30,
    deadline=None,
    suppress_health_check=[
        # Corpus draws embed every chunk via the fake provider — that
        # pushes the per-example data-generation cost above the
        # Hypothesis default, which is expected here.
        HealthCheck.data_too_large,
        HealthCheck.too_slow,
    ],
)
def test_retriever_returns_only_existing_chunks(
    corpus: list[ChunkRecord],
    query: str,
    k: int,
) -> None:
    """Every ``chunk_id`` returned by the retriever exists in the store.

    Validates: Requirements 14.1, 3.11.

    End-to-end flow per example:

    1. Seed a fresh :class:`FakeVectorStore` with ``corpus``.
    2. Build a dense-only :class:`HybridRetriever` (``bm25_index=None``)
       backed by a :class:`FakeEmbeddingsProvider` — same fake the
       store's embeddings were generated with, so cosine similarity
       is meaningful.
    3. Retrieve for :data:`_FIXED_USER_ID` (no symbol filter, so any
       of the ``_SYMBOLS`` can surface).
    4. Assert: every returned hit's ``chunk_id`` is a member of the
       seeded corpus. This is the retriever-side citation-integrity
       property (Req 3.11 / Req 14.1).

    Two side invariants are asserted in the same pass because they
    catch distinct regression modes — see the module docstring.
    """

    async def _body() -> None:
        store = FakeVectorStore()
        await store.upsert(corpus)

        retriever = HybridRetriever(
            vector_store=store,
            embeddings=FakeEmbeddingsProvider(dim=_EMBEDDING_DIM),
            bm25_index=None,
        )

        hits = await retriever.retrieve(
            query,
            filter=RetrievalFilter(user_id=_FIXED_USER_ID),
            k=k,
        )

        known_ids = {c.chunk_id for c in corpus}

        # --- Main property: every returned hit is a real chunk. -------- #
        # A violation here means the retriever fabricated a
        # chunk_id — either by materialising a hit from an empty
        # candidate list, or by mis-copying a field from one chunk
        # onto another's id.
        for hit in hits:
            assert hit.chunk.chunk_id in known_ids, (
                f"retriever returned unknown chunk_id {hit.chunk.chunk_id!r}; "
                f"known ids in corpus: {sorted(known_ids)}"
            )

        # --- Side property 1: namespace containment. ------------------- #
        # A retriever that filters correctly at the store level but
        # mutates records post-fetch would pass the main assertion
        # above while silently leaking cross-tenant content.
        for hit in hits:
            assert hit.chunk.user_id == _FIXED_USER_ID, (
                f"chunk {hit.chunk.chunk_id!r} has user_id "
                f"{hit.chunk.user_id} != filter.user_id {_FIXED_USER_ID}"
            )

        # --- Side property 2: size bound. ------------------------------ #
        # The retriever's contract is "up to k"; a fusion bug that
        # merges two ranked lists without de-duplication could exceed
        # that bound even with all valid ids.
        assert len(hits) <= k, (
            f"retriever returned {len(hits)} hits; expected <= {k}"
        )

    _run(_body())


# --------------------------------------------------------------------------- #
# Regression anchor                                                           #
# --------------------------------------------------------------------------- #


def test_retriever_empty_corpus_returns_no_hits() -> None:
    """Empty corpus ⇒ empty result, regardless of query.

    Validates: Requirement 3.11 (trivially — no chunks exist, so the
    citation-integrity predicate holds vacuously) and Requirement 14.1
    (ensures the property test does not shrink into a vacuous pass on
    the empty-corpus case without an explicit anchor).

    Kept as a regular (non-Hypothesis) test because the assertion is
    binary — a single example is sufficient — and keeping it here
    means a retriever that silently returns a fabricated chunk on an
    empty store fails with a clean, non-randomised error.
    """

    async def _body() -> None:
        store = FakeVectorStore()
        retriever = HybridRetriever(
            vector_store=store,
            embeddings=FakeEmbeddingsProvider(dim=_EMBEDDING_DIM),
            bm25_index=None,
        )
        hits = await retriever.retrieve(
            "anything",
            filter=RetrievalFilter(user_id=_FIXED_USER_ID),
            k=5,
        )
        assert hits == [], f"expected no hits on empty corpus, got {hits!r}"

    asyncio.run(_body())


if __name__ == "__main__":  # pragma: no cover
    # Allow ``python tests/research/test_prop_citation_integrity.py``
    # for quick local iteration during development.
    pytest.main([__file__, "-v"])
