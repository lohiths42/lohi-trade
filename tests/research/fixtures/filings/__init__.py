"""Mini filings corpus used by the Task 18.5 end-to-end smoke test.

The corpus is intentionally tiny — four synthetic "announcement"-style
documents split into eight chunks across two symbols — so the smoke
test runs in sub-second time without requiring real PDFs on disk. The
content is structured Markdown matching the canonical representation
produced by the PDF/HTML parsers (Task 5.7, 5.8) so downstream tests
that also want to exercise the parse path can reuse the same fixtures.

Exports
-------
* :data:`FILINGS` — list of ``(symbol, document_id, chunks)`` tuples
  suitable for feeding directly into :class:`FakeVectorStore.upsert`.
* :func:`build_chunk_records` — helper that materialises
  :class:`ChunkRecord`\\s from the fixture tuples, scoped to a caller-
  supplied ``user_id`` and deterministic embeddings via
  :class:`FakeEmbeddingsProvider`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from src.research.providers.base import ChunkRecord


@dataclass(frozen=True)
class FixtureChunk:
    """One canonical chunk of the synthetic filings corpus."""

    chunk_id: str
    position: int
    text: str


@dataclass(frozen=True)
class FixtureDocument:
    """One synthetic filing document with its constituent chunks."""

    symbol: str
    document_id: UUID
    document_type: str
    chunks: Sequence[FixtureChunk]


# Two symbols, two documents each, two chunks per document — small enough
# to enumerate in a smoke test but large enough that citation integrity
# has something to resolve against.
_RELIANCE_DOC_ID = UUID("11111111-1111-4111-8111-111111111111")
_TCS_DOC_ID = UUID("22222222-2222-4222-8222-222222222222")

FILINGS: list[FixtureDocument] = [
    FixtureDocument(
        symbol="RELIANCE",
        document_id=_RELIANCE_DOC_ID,
        document_type="announcement",
        chunks=[
            FixtureChunk(
                chunk_id="reliance-2024q3-summary",
                position=0,
                text=(
                    "RELIANCE Q3 FY24 consolidated revenue of Rs 2,48,160 crore "
                    "(+2.4% YoY). Operating profit margin 17.1%."
                ),
            ),
            FixtureChunk(
                chunk_id="reliance-2024q3-segments",
                position=1,
                text=(
                    "Digital services segment EBITDA Rs 13,955 crore. "
                    "Retail segment revenue Rs 71,353 crore with 3,073 net "
                    "store additions during the quarter."
                ),
            ),
        ],
    ),
    FixtureDocument(
        symbol="TCS",
        document_id=_TCS_DOC_ID,
        document_type="announcement",
        chunks=[
            FixtureChunk(
                chunk_id="tcs-2024q3-summary",
                position=0,
                text=(
                    "TCS Q3 FY24 revenue of Rs 60,583 crore (+4.0% YoY). "
                    "Operating margin 24.6%. Order book TCV USD 8.1 billion."
                ),
            ),
            FixtureChunk(
                chunk_id="tcs-2024q3-attrition",
                position=1,
                text=(
                    "IT services attrition reduced to 13.3% LTM. Headcount "
                    "stood at 603,305 as of Dec 31, 2023."
                ),
            ),
        ],
    ),
]


def build_chunk_records(
    *,
    user_id: UUID,
    embeddings: object,
) -> list[ChunkRecord]:
    """Materialise :class:`ChunkRecord`\\s from :data:`FILINGS`.

    Parameters
    ----------
    user_id:
        Every chunk is scoped to this user id so the vector store's
        RLS-style filter (Req 3.10, Req 4.5) engages correctly in the
        smoke test.
    embeddings:
        An :class:`~src.research.providers.base.EmbeddingsProvider`
        (typically :class:`FakeEmbeddingsProvider`) whose ``embed`` is
        awaited to produce deterministic vectors. The caller is
        responsible for running this function inside an event loop.

    """
    # ``embeddings.embed`` is async; the caller wraps this helper in
    # ``asyncio.run(...)`` / ``await``. We keep this function sync so
    # the fixture stays a plain data producer — the coroutine is
    # returned by :func:`_build_chunk_records_async`.
    raise RuntimeError(
        "build_chunk_records must not be called directly; "
        "use _build_chunk_records_async from the smoke-test helper.",
    )


async def _build_chunk_records_async(
    *,
    user_id: UUID,
    embeddings: object,
) -> list[ChunkRecord]:
    """Async variant of :func:`build_chunk_records` — the one tests call.

    Iterates every fixture chunk, embeds its text with the injected
    provider, and emits a :class:`ChunkRecord` with:

    * ``chunk_id`` = the fixture chunk's canonical id (stable, content-
      addressable in spirit even though we hard-code the strings for
      readability).
    * ``document_id`` = the fixture document's UUID.
    * ``user_id`` / ``symbol`` = as passed in.
    * ``embedding`` / ``embedding_model`` / ``embedding_dim`` =
      whatever the provider produces.
    """
    records: list[ChunkRecord] = []
    # Embed in one batch per document so the deterministic ordering in
    # :class:`FakeEmbeddingsProvider` is easy to reason about.
    for doc in FILINGS:
        texts = [c.text for c in doc.chunks]
        vectors = await embeddings.embed(texts)  # type: ignore[attr-defined]
        for chunk, vec in zip(doc.chunks, vectors):
            records.append(
                ChunkRecord(
                    chunk_id=chunk.chunk_id,
                    document_id=doc.document_id,
                    user_id=user_id,
                    symbol=doc.symbol,
                    position=chunk.position,
                    token_count=max(1, len(chunk.text) // 4),
                    text=chunk.text,
                    embedding=list(vec),
                    embedding_model=embeddings.model_id,  # type: ignore[attr-defined]
                    embedding_dim=embeddings.dim,  # type: ignore[attr-defined]
                ),
            )
    return records


__all__ = [
    "FILINGS",
    "FixtureChunk",
    "FixtureDocument",
    "_build_chunk_records_async",
]
