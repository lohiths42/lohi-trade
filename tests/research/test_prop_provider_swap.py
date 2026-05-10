r"""Provider-swap invariance — design §17.1 Property 2 / Req 14.2.

The invariant under test: **swapping any provider implementation MUST
NOT change the Pydantic shape callers observe.** Concretely, for every
``(LLMProvider, EmbeddingsProvider, VectorStore)`` pair in our registry,
calling the same method with the same inputs must yield results that:

1. Validate against the same Pydantic model (``Completion``,
   ``CompletionChunk``, or ``ChunkHit``) that defines the
   **Provider_Contract** (Req 2.11).
2. Expose the same set of fields.
3. Hold the same Python *type* in each field — the adapter is free to
   choose the *value*, but not the shape.

This is Property 2 in the design traceability table (design §17.1) and
directly validates Requirement 14.2. It leans on the fakes registered
by Task 2.19 (``FakeLLMProvider``, ``FakeEmbeddingsProvider``,
``FakeVectorStore``) plus an alt ``FakeVectorStoreAlt`` defined inline
here to simulate a vector-store swap without having to stand up a
second backend.

Hypothesis is configured with ``max_examples=30`` and ``deadline=None``
on every Hypothesis test: 30 examples exercises plenty of shape
variation while keeping the test suite well under a second, and
disabling the deadline stops Hypothesis from flaking on cold-start
asyncio overhead or on any future introduction of non-zero
``latency_ms`` knobs in the fakes.

Test roster
-----------
* ``test_llm_complete_shape_invariant_across_providers`` — the core
  Property 2 check: ``complete()`` against two different ``FakeLLMProvider``
  instances returns Pydantic-valid ``Completion``\ s with identical
  field types.
* ``test_llm_stream_chunk_shape_invariant_across_providers`` —
  extends the core check to ``stream()`` / ``CompletionChunk``.
* ``test_embeddings_embed_shape_invariant_across_providers`` —
  ``EmbeddingsProvider.embed`` returns the same ``list[list[float]]``
  shape across swaps; ``model_id`` / ``dim`` are ``str``/``int``.
* ``test_vector_store_upsert_search_shape_invariant_across_backends``
  — ``upsert`` + ``similarity_search`` return ``ChunkHit``\ s with
  identical Pydantic shape across two fake backends.
* ``test_registry_swap_returns_protocol_compliant_types`` — plain
  (non-Hypothesis) integration check that ``install_fakes`` wires the
  production registry such that ``get_llm`` / ``get_embeddings`` /
  ``get_vector_store`` return objects satisfying the runtime-checkable
  Protocols in ``base.py``.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import BaseModel

from src.research.providers.base import (
    ChunkHit,
    ChunkRecord,
    Completion,
    CompletionChunk,
    EmbeddingsProvider,
    LLMParams,
    LLMProvider,
    Message,
    RetrievalFilter,
    VectorStore,
)
from src.research.providers.registry import (
    get_embeddings,
    get_llm,
    get_vector_store,
)
from tests.research.fakes import (
    FakeEmbeddingsProvider,
    FakeLLMProvider,
    FakeVectorStore,
    install_fakes,
)

# --------------------------------------------------------------------------- #
# Alt vector store — simulates a backend swap with different ordering.        #
# --------------------------------------------------------------------------- #


class FakeVectorStoreAlt(FakeVectorStore):
    """Alt ``VectorStore`` that reverses hit order, same shape.

    The provider-swap invariant is a **shape** invariant, not a content
    invariant. Two real vector backends (Chroma vs pgvector vs Qdrant)
    may return the same hits in different orders depending on their
    internal index. Reversing order is a cheap, deterministic way to
    prove two backends with different *behaviour* still yield identical
    ``ChunkHit`` Pydantic shape.
    """

    async def similarity_search(
        self,
        query_vec: list[float],
        *,
        filter: RetrievalFilter,
        k: int,
    ) -> list[ChunkHit]:
        hits = await super().similarity_search(query_vec, filter=filter, k=k)
        return list(reversed(hits))


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _same_field_types(a: Any, b: Any, model_cls: type[BaseModel]) -> bool:
    """True iff ``a`` and ``b`` have identical field-level Python types.

    * Both inputs must be instances of ``model_cls`` — this is the
      Pydantic-validation leg of Req 14.2.
    * For every field declared on ``model_cls.model_fields``,
      ``type(getattr(a, field))`` must equal ``type(getattr(b, field))``.
      This is the shape leg: an adapter may choose to return
      ``finish_reason="stop"`` vs ``"length"``, but both values are
      ``str`` at the Python level, so the caller sees no shape change.
    """
    if not isinstance(a, model_cls) or not isinstance(b, model_cls):
        return False
    for field_name in model_cls.model_fields:
        if type(getattr(a, field_name)) is not type(getattr(b, field_name)):
            return False
    return True


# --------------------------------------------------------------------------- #
# Hypothesis strategies                                                       #
# --------------------------------------------------------------------------- #


@st.composite
def messages_strategy(draw: st.DrawFn) -> list[Message]:
    """Generate a small chat history (1-10 ``Message``s).

    Role is drawn from the three values the ``Message`` model accepts
    (design §3.1); content is drawn from short text (≤200 chars) so
    examples stay readable in failure output.
    """
    size = draw(st.integers(min_value=1, max_value=10))
    roles = st.sampled_from(["system", "user", "assistant"])
    contents = st.text(min_size=0, max_size=200)
    return [
        Message(role=draw(roles), content=draw(contents))
        for _ in range(size)
    ]


@st.composite
def llm_params_strategy(draw: st.DrawFn) -> LLMParams:
    """Generate ``LLMParams`` with each optional field independently set or ``None``.

    Bounds match the validators on ``LLMParams`` in ``base.py``:
    temperature ∈ [0, 2], top_p ∈ [0, 1], max_tokens > 0, timeout_ms > 0.
    """
    return LLMParams(
        temperature=draw(
            st.one_of(st.none(), st.floats(min_value=0.0, max_value=2.0)),
        ),
        max_tokens=draw(
            st.one_of(st.none(), st.integers(min_value=1, max_value=4096)),
        ),
        top_p=draw(st.one_of(st.none(), st.floats(min_value=0.0, max_value=1.0))),
        stop=draw(
            st.one_of(
                st.none(),
                st.lists(st.text(min_size=1, max_size=16), max_size=4),
            ),
        ),
        timeout_ms=draw(
            st.one_of(st.none(), st.integers(min_value=1, max_value=60000)),
        ),
    )


@st.composite
def chunk_record_strategy(draw: st.DrawFn, *, dim: int) -> ChunkRecord:
    """Generate a valid ``ChunkRecord`` with a ``dim``-length embedding.

    Deterministic IDs are not required here — each draw creates a fresh
    ``chunk_id`` string and fresh UUIDs. Position and token_count stay
    in small ranges so Hypothesis shrinks quickly.
    """
    chunk_id = draw(st.text(min_size=1, max_size=64))
    position = draw(st.integers(min_value=0, max_value=1000))
    token_count = draw(st.integers(min_value=0, max_value=2048))
    text = draw(st.text(min_size=0, max_size=200))
    symbol = draw(st.text(min_size=1, max_size=16))
    embedding = draw(
        st.lists(
            st.floats(
                min_value=-1.0,
                max_value=1.0,
                allow_nan=False,
                allow_infinity=False,
            ),
            min_size=dim,
            max_size=dim,
        ),
    )
    return ChunkRecord(
        chunk_id=chunk_id,
        document_id=uuid4(),
        user_id=uuid4(),
        symbol=symbol,
        position=position,
        token_count=token_count,
        text=text,
        embedding=embedding,
        embedding_model="fake-embeddings",
        embedding_dim=dim,
    )


# --------------------------------------------------------------------------- #
# Tests                                                                       #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@given(messages=messages_strategy(), params=llm_params_strategy())
@settings(max_examples=30, deadline=None)
async def test_llm_complete_shape_invariant_across_providers(
    messages: list[Message], params: LLMParams,
) -> None:
    """``LLMProvider.complete`` yields the same ``Completion`` shape across providers.

    Swap two differently-configured ``FakeLLMProvider`` instances —
    different provider name, different canned content, different
    finish_reason — and assert Req 14.2 holds:

    * Both results are ``Completion`` instances.
    * ``Completion.model_validate(result.model_dump())`` succeeds on
      both (self-consistent Pydantic shape, not just construction-time).
    * Both expose the same ``model_fields`` keys (an obvious invariant
      because both are the same class — asserting it documents the
      intent and would catch an accidental subclass drift).
    * ``_same_field_types`` passes — every field holds the same Python
      type in both results.
    """
    provider_a = FakeLLMProvider(
        provider="fake_a",
        model="model-a",
        canned_completion="completion from provider A",
        canned_input_tokens=7,
        canned_output_tokens=13,
        finish_reason="stop",
    )
    provider_b = FakeLLMProvider(
        provider="fake_b",
        model="model-b",
        canned_completion="entirely different completion text",
        canned_input_tokens=21,
        canned_output_tokens=34,
        finish_reason="length",
    )

    result_a = await provider_a.complete(messages, params)
    result_b = await provider_b.complete(messages, params)

    # Shape is self-consistent on both sides — model_dump → model_validate
    # round-trip must succeed. This is stricter than construction-time
    # validation because it also proves the *serialised* shape matches
    # the schema.
    Completion.model_validate(result_a.model_dump())
    Completion.model_validate(result_b.model_dump())

    # Both expose the same field set; documents the shape invariant.
    assert set(Completion.model_fields.keys()) == set(type(result_a).model_fields.keys())
    assert set(type(result_a).model_fields.keys()) == set(
        type(result_b).model_fields.keys(),
    )

    # Per-field Python types match across the swap.
    assert _same_field_types(result_a, result_b, Completion)


@pytest.mark.asyncio
@given(messages=messages_strategy(), params=llm_params_strategy())
@settings(max_examples=30, deadline=None)
async def test_llm_stream_chunk_shape_invariant_across_providers(
    messages: list[Message], params: LLMParams,
) -> None:
    """``LLMProvider.stream`` yields ``CompletionChunk``s with identical shape across providers.

    Iterate both streams fully, then assert every emitted chunk:

    * Validates via ``CompletionChunk.model_validate(chunk.model_dump())``.
    * Shares the same ``model_fields`` set as its peer in the other stream.

    The two providers deliberately emit different numbers of chunks
    (different canned text), so we compare *each chunk independently*
    against the ``CompletionChunk`` model — the invariant is per-chunk
    shape, not stream length.
    """
    provider_a = FakeLLMProvider(
        provider="fake_a",
        model="model-a",
        canned_completion="alpha beta gamma",
    )
    provider_b = FakeLLMProvider(
        provider="fake_b",
        model="model-b",
        canned_completion="one two three four five",
    )

    chunks_a: list[CompletionChunk] = []
    async for chunk in provider_a.stream(messages, params):
        chunks_a.append(chunk)

    chunks_b: list[CompletionChunk] = []
    async for chunk in provider_b.stream(messages, params):
        chunks_b.append(chunk)

    # Both providers must actually stream something for the shape
    # check to be meaningful; the canned completions above guarantee
    # at least one chunk each.
    assert chunks_a, "provider A produced no chunks"
    assert chunks_b, "provider B produced no chunks"

    expected_fields = set(CompletionChunk.model_fields.keys())

    for chunk in chunks_a:
        CompletionChunk.model_validate(chunk.model_dump())
        assert set(type(chunk).model_fields.keys()) == expected_fields
    for chunk in chunks_b:
        CompletionChunk.model_validate(chunk.model_dump())
        assert set(type(chunk).model_fields.keys()) == expected_fields

    # Pairwise type check across the two streams: for every index that
    # exists on both sides, the shape must match.
    for ca, cb in zip(chunks_a, chunks_b):
        assert _same_field_types(ca, cb, CompletionChunk)


@pytest.mark.asyncio
@given(
    texts=st.lists(st.text(min_size=0, max_size=200), min_size=1, max_size=10),
)
@settings(max_examples=30, deadline=None)
async def test_embeddings_embed_shape_invariant_across_providers(
    texts: list[str],
) -> None:
    """``EmbeddingsProvider.embed`` yields the same shape across providers.

    Two ``FakeEmbeddingsProvider`` instances with different ``model``
    names but the same ``dim``. For any generated list of texts:

    * ``embed`` returns ``list[list[float]]`` on both.
    * Outer length equals ``len(texts)`` on both.
    * Every inner list is exactly ``dim`` floats on both.
    * ``model_id`` is a ``str`` on both; ``dim`` is an ``int`` on both.

    ``EmbeddingsProvider`` is a Protocol (not a Pydantic model), so the
    "Pydantic validation" leg of the invariant collapses to runtime
    type assertions on the structured result.
    """
    dim = 384
    provider_a = FakeEmbeddingsProvider(model="emb-model-a", dim=dim)
    provider_b = FakeEmbeddingsProvider(model="emb-model-b", dim=dim)

    result_a = await provider_a.embed(texts)
    result_b = await provider_b.embed(texts)

    # Outer shape
    assert isinstance(result_a, list) and isinstance(result_b, list)
    assert len(result_a) == len(texts)
    assert len(result_b) == len(texts)

    # Inner shape: every vector is a list of dim floats in both backends.
    for vec in result_a:
        assert isinstance(vec, list)
        assert len(vec) == dim
        assert all(isinstance(x, float) for x in vec)
    for vec in result_b:
        assert isinstance(vec, list)
        assert len(vec) == dim
        assert all(isinstance(x, float) for x in vec)

    # Metadata shape.
    assert isinstance(provider_a.model_id, str)
    assert isinstance(provider_b.model_id, str)
    assert isinstance(provider_a.dim, int)
    assert isinstance(provider_b.dim, int)
    assert provider_a.dim == provider_b.dim == dim


@pytest.mark.asyncio
@given(
    chunks=st.lists(chunk_record_strategy(dim=384), min_size=1, max_size=3),
)
@settings(
    max_examples=30,
    deadline=None,
    # Generating a handful of 384-dim float embeddings per example is
    # our actual input; Hypothesis's entropy accounting flags that as
    # "too large" even though runtime is sub-second. Suppress the
    # health check — the shape invariant is independent of corpus size.
    suppress_health_check=[HealthCheck.data_too_large],
)
async def test_vector_store_upsert_search_shape_invariant_across_backends(
    chunks: list[ChunkRecord],
) -> None:
    """``VectorStore`` returns identically-shaped ``ChunkHit``s across backends.

    Upsert the same generated ``ChunkRecord`` set into two stores —
    ``FakeVectorStore`` and ``FakeVectorStoreAlt`` (which reverses hit
    order but preserves shape) — then run the same similarity search on
    both. Every returned hit must:

    * Validate via ``ChunkHit.model_validate(hit.model_dump())``.
    * Expose the same ``model_fields`` set.
    * Match field-level Python types pairwise (``_same_field_types``)
      when paired index-for-index with the alt backend's hits.

    We normalise ``user_id`` and ``symbol`` across all generated chunks
    so the retrieval filter actually returns something; otherwise the
    test degenerates to comparing two empty lists, which would still
    pass but wouldn't exercise the ``ChunkHit`` shape invariant.
    """
    shared_user_id: UUID = uuid4()
    shared_symbol = "RELIANCE"
    normalised = [
        c.model_copy(update={"user_id": shared_user_id, "symbol": shared_symbol})
        for c in chunks
    ]

    store_a = FakeVectorStore()
    store_b = FakeVectorStoreAlt()
    await store_a.upsert(normalised)
    await store_b.upsert(normalised)

    # Query vector reuses the first chunk's embedding so we're
    # guaranteed at least one non-zero-similarity hit.
    query_vec = list(normalised[0].embedding)
    retrieval_filter = RetrievalFilter(user_id=shared_user_id, symbol=shared_symbol)
    k = len(normalised)

    hits_a = await store_a.similarity_search(query_vec, filter=retrieval_filter, k=k)
    hits_b = await store_b.similarity_search(query_vec, filter=retrieval_filter, k=k)

    expected_fields = set(ChunkHit.model_fields.keys())

    # Every hit in both backends validates and shares the same field set.
    for hit in hits_a:
        ChunkHit.model_validate(hit.model_dump())
        assert set(type(hit).model_fields.keys()) == expected_fields
    for hit in hits_b:
        ChunkHit.model_validate(hit.model_dump())
        assert set(type(hit).model_fields.keys()) == expected_fields

    # Both backends see the same rows under the same filter, so the
    # returned count must match — content order may differ (alt reverses
    # it), but length is a shape-level property we can assert.
    assert len(hits_a) == len(hits_b)

    # Per-field type check pairwise. Order differs between the two
    # backends, but all ``ChunkHit`` instances share the same field
    # types by construction, so comparing index-for-index is still a
    # valid shape check.
    for ha, hb in zip(hits_a, hits_b):
        assert _same_field_types(ha, hb, ChunkHit)


# --------------------------------------------------------------------------- #
# Registry-level shape check (plain, non-Hypothesis)                          #
# --------------------------------------------------------------------------- #


def test_registry_swap_returns_protocol_compliant_types() -> None:
    """``install_fakes`` wires the production registry to Protocol-compliant fakes.

    The four Hypothesis tests above exercise provider-swap invariance at
    the **instance** layer — they build fakes directly and compare
    method-level output shape. This test closes the loop one layer up:
    after :func:`install_fakes` seeds the production registry
    (``src.research.providers.registry``) with ``"fake"`` entries, the
    public builders :func:`get_llm`, :func:`get_embeddings`, and
    :func:`get_vector_store` must return objects that satisfy the
    ``runtime_checkable`` Protocols declared in ``base.py``.

    That is the integration point Req 14.2 protects: callers all go
    through the registry builders, so the "swapping providers must not
    change the shape" guarantee only holds if the builders themselves
    return Protocol-compliant instances. A regression here — e.g. a
    future refactor that makes ``get_llm`` return a bare ``dict`` or a
    subclass that drops a method — would invalidate every downstream
    swap test.

    Not a Hypothesis test: there is nothing to generate. The assertion
    is a single ``isinstance`` against each Protocol, which is the
    cheapest possible shape check and the one the design explicitly
    calls out (design §17.1 row 2).
    """
    install_fakes()

    llm = get_llm({"provider": "fake"})
    assert isinstance(llm, LLMProvider)
    # ``FakeLLMProvider`` is the concrete class we expect install_fakes
    # to wire up; assert this separately so a silent factory swap
    # doesn't pass the Protocol check by accident (every class is a
    # trivial Protocol conformer via duck typing on ``runtime_checkable``).
    assert isinstance(llm, FakeLLMProvider)

    emb = get_embeddings({"provider": "fake"})
    assert isinstance(emb, EmbeddingsProvider)
    assert isinstance(emb, FakeEmbeddingsProvider)

    vec = get_vector_store({"backend": "fake"})
    assert isinstance(vec, VectorStore)
    assert isinstance(vec, FakeVectorStore)
