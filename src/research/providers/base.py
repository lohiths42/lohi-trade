"""Pluggable provider contracts — LLM, embeddings, vector store (design §3.1).

This module defines the Pydantic-validated data shapes and `typing.Protocol`
abstractions that every concrete provider adapter in
`src/research/providers/{llm,embeddings,vector_store}/` must conform to.

Contract summary (cross-referenced to requirements.md):

- ``LLMProvider``         — Req 2.1  : ``complete()`` + ``stream()``.
- ``EmbeddingsProvider``  — Req 2.2  : ``embed()`` + ``model_id`` + ``dim``.
- ``VectorStore``         — Req 2.3  : ``upsert`` / ``similarity_search`` /
                                        ``delete_by_filter`` / ``count``.
- ``Completion``          — Req 2.11 : the **Provider_Contract** Pydantic
                                        model. Swapping providers must not
                                        change this shape (Req 14.2 tests
                                        this invariant).
- ``ProviderAuthError``   — Req 2.10 : re-exported from ``errors`` so
                                        adapter authors only import from
                                        ``.base``.

All models are Pydantic v2 (``BaseModel`` + ``ConfigDict``) to match the
project convention (`backend-gateway/app/models/base.py`).

Registration of concrete adapters lives in ``registry.py`` (Task 2.2);
this module is deliberately framework-free and has no runtime imports of
concrete backends.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .errors import ProviderAuthError

# --------------------------------------------------------------------------- #
# LLM contract                                                                #
# --------------------------------------------------------------------------- #


class Message(BaseModel):
    """A single chat message exchanged with an ``LLMProvider`` (design §3.1).

    The ``role`` values follow the OpenAI-compatible convention used by
    every shipped adapter (NVIDIA NIM, OpenAI, Anthropic, Gemini, Groq,
    Together, OpenRouter, Ollama — see design §3.1 / Req 2.4). Tool-call
    wire formats are intentionally excluded: the Guardrail_Layer strips
    tool-call tokens before they reach the model (design §3.6, Req 16.9).
    """

    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant"] = Field(
        ...,
        description="Speaker role. 'system' messages carry the versioned "
        "prompt template (design §3.9); the Guardrail_Layer refuses any "
        "user-supplied 'system' before it reaches the envelope (Req 16.3).",
    )
    content: str = Field(
        ...,
        description="Plain-text message body. Template rendering and "
        "citation-marker insertion happen upstream of this model.",
    )


class LLMParams(BaseModel):
    """Per-call generation parameters surfaced to an ``LLMProvider``.

    Field list follows the per-agent configuration block called out in
    design §3.5 / Req 12.1–12.2 — ``research.agents.<name>.{temperature,
    max_tokens, timeout_ms}`` — plus the optional knobs every shipped
    adapter needs to implement ``complete``/``stream`` faithfully.

    All fields are optional so call sites can start with defaults and
    let the adapter fall back to provider defaults; adapters MUST NOT
    add new required fields without a matching requirement change.
    """

    model_config = ConfigDict(extra="forbid")

    temperature: float | None = Field(
        default=None,
        ge=0.0,
        le=2.0,
        description="Sampling temperature. Default lives in settings.yaml.",
    )
    max_tokens: int | None = Field(
        default=None,
        gt=0,
        description="Upper bound on generated tokens (per-agent cap, Req 12.3).",
    )
    top_p: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Nucleus-sampling cutoff.",
    )
    stop: list[str] | None = Field(
        default=None,
        description="Stop sequences; adapters translate to their native form.",
    )
    timeout_ms: int | None = Field(
        default=None,
        gt=0,
        description="Per-call timeout in milliseconds (design §3.5, Req 12.2).",
    )
    stream: bool = Field(
        default=False,
        description="Client hint; `.stream()` ignores this and always streams.",
    )
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="Escape hatch for provider-specific knobs (e.g. NIM "
        "`presence_penalty`). Adapters MAY ignore unknown keys.",
    )


class Completion(BaseModel):
    """The **Provider_Contract** returned by ``LLMProvider.complete`` (Req 2.11).

    Every concrete LLM adapter MUST return exactly this shape; the
    provider-swap property test in Task 2.20 / Req 14.2 asserts that
    swapping providers does not change this contract.
    """

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(..., description="Registry name, e.g. 'nvidia_nim'.")
    model: str = Field(..., description="Provider-side model identifier.")
    content: str = Field(..., description="Full assistant text.")
    input_tokens: int = Field(
        ...,
        ge=0,
        description="Prompt-side token count as reported by the provider.",
    )
    output_tokens: int = Field(
        ...,
        ge=0,
        description="Completion-side token count as reported by the provider.",
    )
    finish_reason: Literal["stop", "length", "refusal", "error"] = Field(
        ...,
        description="Normalised finish reason across all shipped adapters.",
    )


class CompletionChunk(BaseModel):
    """A single streamed delta emitted by ``LLMProvider.stream`` (design §3.1)."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(..., description="Registry name of the emitting adapter.")
    model: str = Field(..., description="Provider-side model identifier.")
    delta: str = Field(..., description="Incremental text fragment.")
    index: int = Field(
        ...,
        ge=0,
        description="Zero-based position of this chunk within the stream.",
    )


@runtime_checkable
class LLMProvider(Protocol):
    """Abstract LLM backend (Req 2.1, design §3.1).

    Implementations live under ``src/research/providers/llm/*.py`` — one
    file per backend — and are registered with a one-line entry in
    ``registry.py`` (Req 2.12).

    Implementations MUST raise ``ProviderAuthError`` on 401/403 from the
    upstream API rather than falling back silently (Req 2.10).
    """

    async def complete(
        self,
        messages: list[Message],
        params: LLMParams,
    ) -> Completion:
        """Produce a single non-streamed ``Completion`` (Req 2.11)."""
        ...

    def stream(
        self,
        messages: list[Message],
        params: LLMParams,
    ) -> AsyncIterator[CompletionChunk]:
        """Produce an async iterator of ``CompletionChunk`` deltas.

        Declared without ``async def`` so concrete adapters can be
        written as ``async def`` generators (the idiomatic
        ``AsyncIterator`` factory in Python 3.11+); both spellings
        satisfy the protocol at runtime.
        """
        ...


# --------------------------------------------------------------------------- #
# Embeddings contract                                                         #
# --------------------------------------------------------------------------- #


@runtime_checkable
class EmbeddingsProvider(Protocol):
    """Abstract embeddings backend (Req 2.2, design §3.1).

    Default local implementation is ``sentence-transformers`` with
    ``BAAI/bge-small-en-v1.5`` (384 dim, Req 2.5, Task 2.11). Swapping
    embeddings providers must not change the shape returned by ``embed``
    (Req 14.2).
    """

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed ``texts`` and return one float vector per input."""
        ...

    @property
    def model_id(self) -> str:
        """Stable identifier used in cache keys (design §3.11, Req 5.6)."""
        ...

    @property
    def dim(self) -> int:
        """Embedding dimensionality; wired into ``VECTOR(dim)`` (Req 2.14)."""
        ...


# --------------------------------------------------------------------------- #
# Vector-store contract                                                       #
# --------------------------------------------------------------------------- #


class ChunkRecord(BaseModel):
    """A single indexed chunk persisted to a ``VectorStore`` (design §3.3).

    ``chunk_id`` is derived deterministically as
    ``sha256(document_sha256 || chunker_version || position)`` so that
    re-ingesting unchanged content yields the same IDs and
    ``VectorStore.upsert`` is a true upsert (Req 3.12, Req 14.4).
    """

    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(
        ...,
        description="Stable: sha256(document_sha256 || chunker_version || position).",
    )
    document_id: UUID = Field(..., description="FK to research_documents (Req 3.4).")
    user_id: UUID = Field(
        ...,
        description="Namespace key; every query scopes by user_id (Req 3.10, 4.5).",
    )
    symbol: str = Field(..., description="Namespace key, e.g. 'RELIANCE'.")
    position: int = Field(
        ...,
        ge=0,
        description="Zero-based chunk position within the source doc.",
    )
    token_count: int = Field(..., ge=0, description="Tokens in ``text``.")
    text: str = Field(..., description="Chunk body as stored in the vector backend.")
    embedding: list[float] = Field(
        ...,
        description="Embedding vector produced by ``EmbeddingsProvider.embed``.",
    )
    embedding_model: str = Field(
        ...,
        description="``EmbeddingsProvider.model_id`` at ingest time (design §3.3).",
    )
    embedding_dim: int = Field(
        ...,
        gt=0,
        description="Length of ``embedding``; must equal the provider's ``dim``.",
    )


class RetrievalFilter(BaseModel):
    """Filter predicate applied to every ``VectorStore`` operation (Req 3.10).

    ``user_id`` is mandatory so a forgotten filter cannot leak across
    tenants; optional fields narrow further by symbol / document type /
    similarity floor.
    """

    model_config = ConfigDict(extra="forbid")

    user_id: UUID = Field(..., description="Tenant scope (mandatory, Req 4.5).")
    symbol: str | None = Field(default=None, description="Optional symbol scope.")
    document_type: str | None = Field(
        default=None,
        description="Optional canonical document_type narrowing (design §3.2).",
    )
    min_score: float | None = Field(
        default=None,
        description="Similarity floor (design §3.3, Req 16.24).",
    )


class ChunkHit(BaseModel):
    """A scored retrieval hit returned by ``VectorStore.similarity_search``.

    Per-strategy ranks (``bm25_rank``, ``dense_rank``, ``rerank_rank``)
    are optional so BM25-only / dense-only / reranked paths all use the
    same shape (design §3.3).
    """

    model_config = ConfigDict(extra="forbid")

    chunk: ChunkRecord = Field(..., description="The matched chunk.")
    score: float = Field(..., description="Final fused score used for ordering.")
    bm25_rank: int | None = Field(
        default=None,
        ge=1,
        description="BM25 rank (1-based) if available.",
    )
    dense_rank: int | None = Field(
        default=None,
        ge=1,
        description="Dense-search rank (1-based) if available.",
    )
    rerank_rank: int | None = Field(
        default=None,
        ge=1,
        description="Cross-encoder rank (1-based) if available.",
    )


@runtime_checkable
class VectorStore(Protocol):
    """Abstract vector-store backend (Req 2.3, design §3.1).

    Implementations under ``src/research/providers/vector_store/`` cover
    Chroma (default self-hosted, Req 2.13), pgvector (default SaaS,
    Req 2.14), Qdrant and LanceDB (optional). Every call MUST scope by
    ``filter.user_id`` to preserve tenant isolation (Req 3.10, Req 4.5).
    """

    async def upsert(self, chunks: list[ChunkRecord]) -> None:
        """Insert or update ``chunks``; idempotent by ``chunk_id`` (Req 3.12)."""
        ...

    async def similarity_search(
        self,
        query_vec: list[float],
        *,
        filter: RetrievalFilter,
        k: int,
    ) -> list[ChunkHit]:
        """Return up to ``k`` nearest neighbours under ``filter`` (Req 3.8)."""
        ...

    async def delete_by_filter(self, filter: RetrievalFilter) -> int:
        """Delete matching rows; returns count deleted (used by memory.forget)."""
        ...

    async def count(self, filter: RetrievalFilter) -> int:
        """Count matching rows; used by the health endpoint (design §5.1)."""
        ...


__all__ = [
    # Errors (re-export so adapter authors only import from .base)
    "ProviderAuthError",
    # LLM contract
    "Message",
    "LLMParams",
    "Completion",
    "CompletionChunk",
    "LLMProvider",
    # Embeddings contract
    "EmbeddingsProvider",
    # Vector-store contract
    "ChunkRecord",
    "RetrievalFilter",
    "ChunkHit",
    "VectorStore",
]
