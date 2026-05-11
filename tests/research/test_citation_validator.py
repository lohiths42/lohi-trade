"""Unit tests for the citation validator (Task 11.2).

Exercises the core contract from design §3.8 / Req 3.11 / Req 14.1:
**every cited ``chunk_id`` must resolve in the active VectorStore
under the run's ``(user_id, symbol)`` namespace.** Violations surface
as :class:`UnsupportedClaim` entries with ``reason="citation_mismatch"``
so the Orchestrator's re-synthesis loop (design §11.2) can feed them
back into the Report_Synthesizer.

These tests use the in-memory :class:`FakeVectorStore` (Task 2.19) so
the validator is driven against the real protocol surface without
reaching for network-bound adapters.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import UUID

import pytest

from src.research.providers.base import ChunkRecord
from src.research.validators.citation_validator import (
    CitationValidator,
    validate_citations,
)
from src.research.validators.types import UnsupportedClaim
from tests.research.fakes import FakeVectorStore

# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


# Pinned UUIDs keep counter-examples stable across test runs when a
# regression fires. The validator never inspects ``document_id`` so
# every seeded chunk may share the same value.
_USER_A = UUID("11111111-1111-1111-1111-111111111111")
_USER_B = UUID("22222222-2222-2222-2222-222222222222")
_DOCUMENT_ID = UUID("33333333-3333-3333-3333-333333333333")
_SYMBOL = "RELIANCE"
_OTHER_SYMBOL = "TCS"

# Default embedding dim — matches ``BAAI/bge-small-en-v1.5`` / the
# project's :class:`FakeEmbeddingsProvider` default. The citation
# validator only cares that the dim matches what the store has, so
# keeping a single constant here avoids drift between seeded chunks
# and the zero-vector probe the validator issues internally.
_DIM = 384


@dataclass(frozen=True)
class _FakeCitation:
    """Duck-typed citation — only ``.chunk_id`` is read by the validator.

    Mirrors the shape the full :class:`Citation` Pydantic model (Task
    13.8) exposes, minus fields the validator does not inspect. A
    ``frozen`` dataclass keeps test setup explicit and guards against
    accidental in-place mutation in the arrange section.
    """

    chunk_id: str


def _chunk(chunk_id: str, *, user_id: UUID = _USER_A, symbol: str = _SYMBOL) -> ChunkRecord:
    """Build a :class:`ChunkRecord` with deterministic per-id fields.

    The embedding is a degenerate zero-ish vector because the
    validator never scores relevance — it only reads ``chunk_id``.
    Using a non-zero first element sidesteps the ``FakeVectorStore``
    zero-norm guard (which would return score 0.0 for every chunk)
    so the enumeration path exercised by the validator traverses the
    same cosine ordering real adapters use.
    """
    emb = [0.0] * _DIM
    # A single non-zero component guarantees non-zero norm without
    # biasing the ordering — all chunks receive the same degenerate
    # vector so they tie on score and come out in insertion order.
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
    """Drive an async coroutine to completion inside a sync test.

    The validator is async because the underlying :class:`VectorStore`
    protocol is async. Wrapping every test body in :func:`asyncio.run`
    keeps each example's event loop isolated and matches the pattern
    the rest of ``tests/research/`` uses for protocol-level tests
    (see ``test_prop_citation_integrity.py``).
    """
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# Happy path                                                                  #
# --------------------------------------------------------------------------- #


class TestValidateCitationsHappyPath:
    """Well-formed briefs with resolvable citations produce zero violations."""

    def test_single_resolved_citation_is_supported(self) -> None:
        async def _body() -> None:
            store = FakeVectorStore()
            await store.upsert([_chunk("chunk-alpha")])
            result = await validate_citations(
                vector_store=store,
                brief=[_FakeCitation(chunk_id="chunk-alpha")],
                user_id=_USER_A,
                symbol=_SYMBOL,
                embedding_dim=_DIM,
            )
            assert result == []

        _run(_body())

    def test_multiple_resolved_citations_are_supported(self) -> None:
        async def _body() -> None:
            store = FakeVectorStore()
            await store.upsert(
                [_chunk("a"), _chunk("b"), _chunk("c"), _chunk("d")],
            )
            brief = [_FakeCitation(chunk_id=x) for x in ("a", "c", "d")]
            result = await validate_citations(
                vector_store=store,
                brief=brief,
                user_id=_USER_A,
                symbol=_SYMBOL,
                embedding_dim=_DIM,
            )
            assert result == []

        _run(_body())

    def test_no_citations_yields_no_violations(self) -> None:
        """A brief with zero citations passes vacuously (Req 1.6 partial runs)."""

        async def _body() -> None:
            store = FakeVectorStore()
            await store.upsert([_chunk("a")])
            result = await validate_citations(
                vector_store=store,
                brief=[],
                user_id=_USER_A,
                symbol=_SYMBOL,
                embedding_dim=_DIM,
            )
            assert result == []

        _run(_body())


# --------------------------------------------------------------------------- #
# Failure modes                                                               #
# --------------------------------------------------------------------------- #


class TestValidateCitationsViolations:
    """Every citation that cannot resolve yields exactly one violation."""

    def test_unknown_chunk_id_is_flagged(self) -> None:
        async def _body() -> None:
            store = FakeVectorStore()
            await store.upsert([_chunk("known")])
            result = await validate_citations(
                vector_store=store,
                brief=[_FakeCitation(chunk_id="not-indexed")],
                user_id=_USER_A,
                symbol=_SYMBOL,
                embedding_dim=_DIM,
            )
            assert len(result) == 1
            v = result[0]
            assert isinstance(v, UnsupportedClaim)
            assert v.reason == "citation_mismatch"
            assert v.claim_text == "not-indexed"

        _run(_body())

    def test_mix_of_known_and_unknown_is_partitioned(self) -> None:
        """Each unknown id produces one violation; known ids stay silent."""

        async def _body() -> None:
            store = FakeVectorStore()
            await store.upsert([_chunk("a"), _chunk("b")])
            brief = [
                _FakeCitation(chunk_id="a"),
                _FakeCitation(chunk_id="ghost-1"),
                _FakeCitation(chunk_id="b"),
                _FakeCitation(chunk_id="ghost-2"),
            ]
            result = await validate_citations(
                vector_store=store,
                brief=brief,
                user_id=_USER_A,
                symbol=_SYMBOL,
                embedding_dim=_DIM,
            )
            assert [v.claim_text for v in result] == ["ghost-1", "ghost-2"]
            assert all(v.reason == "citation_mismatch" for v in result)

        _run(_body())

    def test_empty_string_chunk_id_is_flagged(self) -> None:
        """Whitespace-only ids cannot resolve and must fail explicitly."""

        async def _body() -> None:
            store = FakeVectorStore()
            await store.upsert([_chunk("real")])
            result = await validate_citations(
                vector_store=store,
                brief=[_FakeCitation(chunk_id="   ")],
                user_id=_USER_A,
                symbol=_SYMBOL,
                embedding_dim=_DIM,
            )
            assert len(result) == 1
            assert result[0].reason == "citation_mismatch"

        _run(_body())

    def test_all_unknown_flags_every_citation(self) -> None:
        async def _body() -> None:
            store = FakeVectorStore()
            # Namespace is empty — every citation necessarily fails.
            brief = [_FakeCitation(chunk_id=f"c{i}") for i in range(5)]
            result = await validate_citations(
                vector_store=store,
                brief=brief,
                user_id=_USER_A,
                symbol=_SYMBOL,
                embedding_dim=_DIM,
            )
            assert len(result) == 5
            assert {v.claim_text for v in result} == {"c0", "c1", "c2", "c3", "c4"}

        _run(_body())


# --------------------------------------------------------------------------- #
# Namespace scoping                                                           #
# --------------------------------------------------------------------------- #


class TestNamespaceScoping:
    """A citation resolves only inside its ``(user_id, symbol)`` namespace."""

    def test_other_users_chunk_does_not_resolve(self) -> None:
        """User A's brief cannot cite a chunk that belongs to User B.

        This guards the validator against the cross-tenant-leak
        regression that Req 3.10 / Req 4.5 exist to prevent.
        """

        async def _body() -> None:
            store = FakeVectorStore()
            await store.upsert([_chunk("shared-id", user_id=_USER_B)])
            result = await validate_citations(
                vector_store=store,
                brief=[_FakeCitation(chunk_id="shared-id")],
                user_id=_USER_A,
                symbol=_SYMBOL,
                embedding_dim=_DIM,
            )
            assert len(result) == 1
            assert result[0].reason == "citation_mismatch"

        _run(_body())

    def test_other_symbols_chunk_does_not_resolve(self) -> None:
        """A run scoped to RELIANCE cannot cite a TCS chunk."""

        async def _body() -> None:
            store = FakeVectorStore()
            await store.upsert([_chunk("tcs-1", symbol=_OTHER_SYMBOL)])
            result = await validate_citations(
                vector_store=store,
                brief=[_FakeCitation(chunk_id="tcs-1")],
                user_id=_USER_A,
                symbol=_SYMBOL,
                embedding_dim=_DIM,
            )
            assert len(result) == 1
            assert result[0].reason == "citation_mismatch"

        _run(_body())

    def test_matching_user_and_symbol_resolves(self) -> None:
        async def _body() -> None:
            store = FakeVectorStore()
            await store.upsert(
                [
                    _chunk("in-scope", user_id=_USER_A, symbol=_SYMBOL),
                    _chunk("other-user", user_id=_USER_B, symbol=_SYMBOL),
                    _chunk("other-symbol", user_id=_USER_A, symbol=_OTHER_SYMBOL),
                ],
            )
            result = await validate_citations(
                vector_store=store,
                brief=[_FakeCitation(chunk_id="in-scope")],
                user_id=_USER_A,
                symbol=_SYMBOL,
                embedding_dim=_DIM,
            )
            assert result == []

        _run(_body())


# --------------------------------------------------------------------------- #
# Accessor shapes                                                             #
# --------------------------------------------------------------------------- #


class TestBriefAccessorShapes:
    """The validator duck-types across list / mapping / object inputs."""

    def test_mapping_with_citations_key(self) -> None:
        async def _body() -> None:
            store = FakeVectorStore()
            await store.upsert([_chunk("a")])
            brief = {"citations": [_FakeCitation(chunk_id="a")]}
            result = await validate_citations(
                vector_store=store,
                brief=brief,
                user_id=_USER_A,
                symbol=_SYMBOL,
                embedding_dim=_DIM,
            )
            assert result == []

        _run(_body())

    def test_object_with_citations_attribute(self) -> None:
        async def _body() -> None:
            store = FakeVectorStore()
            await store.upsert([_chunk("a")])

            class BriefLike:
                citations = [_FakeCitation(chunk_id="a"), _FakeCitation(chunk_id="missing")]

            result = await validate_citations(
                vector_store=store,
                brief=BriefLike(),
                user_id=_USER_A,
                symbol=_SYMBOL,
                embedding_dim=_DIM,
            )
            assert len(result) == 1
            assert result[0].claim_text == "missing"

        _run(_body())

    def test_missing_citations_attribute_is_empty(self) -> None:
        """A brief object with no ``.citations`` yields zero violations."""

        async def _body() -> None:
            store = FakeVectorStore()
            await store.upsert([_chunk("a")])

            class BriefLike:
                # No ``citations`` field at all.
                pass

            result = await validate_citations(
                vector_store=store,
                brief=BriefLike(),
                user_id=_USER_A,
                symbol=_SYMBOL,
                embedding_dim=_DIM,
            )
            assert result == []

        _run(_body())

    def test_tuple_of_citations(self) -> None:
        async def _body() -> None:
            store = FakeVectorStore()
            await store.upsert([_chunk("a"), _chunk("b")])
            result = await validate_citations(
                vector_store=store,
                brief=(_FakeCitation(chunk_id="a"), _FakeCitation(chunk_id="b")),
                user_id=_USER_A,
                symbol=_SYMBOL,
                embedding_dim=_DIM,
            )
            assert result == []

        _run(_body())


# --------------------------------------------------------------------------- #
# Violation shape                                                             #
# --------------------------------------------------------------------------- #


class TestUnsupportedClaimShape:
    """The emitted violation conforms to the shared ``UnsupportedClaim`` contract."""

    def test_violation_fields_are_well_formed(self) -> None:
        async def _body() -> None:
            store = FakeVectorStore()
            result = await validate_citations(
                vector_store=store,
                brief=[_FakeCitation(chunk_id="ghost-007")],
                user_id=_USER_A,
                symbol=_SYMBOL,
                embedding_dim=_DIM,
            )
            assert len(result) == 1
            v = result[0]
            # Pydantic validators on ``UnsupportedClaim`` enforce:
            # * non-empty section + claim_text,
            # * strictly positive end_offset > start_offset,
            # * reason ∈ :data:`UnsupportedReason`.
            assert v.section != ""
            assert v.claim_text == "ghost-007"
            assert v.start_offset == 0
            assert v.end_offset == len("ghost-007")
            assert v.reason == "citation_mismatch"

        _run(_body())

    def test_order_is_stable(self) -> None:
        """Violations are emitted in brief-order for deterministic diffs."""

        async def _body() -> None:
            store = FakeVectorStore()
            await store.upsert([_chunk("real")])
            brief = [_FakeCitation(chunk_id=f"ghost-{i}") for i in range(4)]
            result = await validate_citations(
                vector_store=store,
                brief=brief,
                user_id=_USER_A,
                symbol=_SYMBOL,
                embedding_dim=_DIM,
            )
            assert [v.claim_text for v in result] == [
                "ghost-0",
                "ghost-1",
                "ghost-2",
                "ghost-3",
            ]

        _run(_body())


# --------------------------------------------------------------------------- #
# Class-based API                                                             #
# --------------------------------------------------------------------------- #


class TestCitationValidatorClass:
    """The :class:`CitationValidator` instance-level API mirrors the helper."""

    def test_class_api_matches_helper(self) -> None:
        async def _body() -> None:
            store = FakeVectorStore()
            await store.upsert([_chunk("a")])
            validator = CitationValidator(store, embedding_dim=_DIM)
            brief = [_FakeCitation(chunk_id="a"), _FakeCitation(chunk_id="missing")]
            result = await validator.validate(
                brief=brief,
                user_id=_USER_A,
                symbol=_SYMBOL,
            )
            assert len(result) == 1
            assert result[0].claim_text == "missing"

        _run(_body())

    def test_validator_is_reusable_across_runs(self) -> None:
        """A single validator instance handles multiple sequential calls."""

        async def _body() -> None:
            store = FakeVectorStore()
            await store.upsert([_chunk("a")])
            validator = CitationValidator(store, embedding_dim=_DIM)

            # First run: resolves cleanly.
            r1 = await validator.validate(
                brief=[_FakeCitation(chunk_id="a")],
                user_id=_USER_A,
                symbol=_SYMBOL,
            )
            assert r1 == []

            # Second run: flags unknowns without stale state from the first.
            r2 = await validator.validate(
                brief=[_FakeCitation(chunk_id="missing")],
                user_id=_USER_A,
                symbol=_SYMBOL,
            )
            assert len(r2) == 1
            assert r2[0].claim_text == "missing"

        _run(_body())


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
