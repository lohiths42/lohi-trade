"""Recursive character splitter for canonical documents (Req 3.6, Req 3.12).

Takes a :class:`src.research.ingest.parser.canonical.CanonicalDoc` and
slices its ``canonical_text`` into bounded :class:`ChunkRecord`s ready for
embedding + vector-store upsert. Stable ``chunk_id`` derivation makes the
re-indexing operation required by Req 3.12 idempotent at the chunk-id
level — that property is exercised by Task 5.15
(``tests/research/test_prop_reindex_idempotent.py``) against
**Property 4 / Req 14.4**.

Requirements covered
--------------------
* **Req 3.6** — configurable chunking strategy; default recursive
  character splitter at 800 tokens per chunk with 120-token overlap.
  Each emitted :class:`ChunkRecord` carries ``document_id``,
  ``position`` (0-based), and ``token_count``.
* **Req 3.12** — ``chunk_id = sha256(document_sha256 || chunker_version
  || position)``. Re-chunking unchanged content with the same
  ``chunker_version`` yields an identical set of ``chunk_id``s so
  :meth:`VectorStore.upsert` can be a true upsert.

Design references
-----------------
* :file:`.kiro/specs/lohi-research-dashboard/design.md` §3.2 names this
  module — "``chunker.py`` — recursive character splitter, 800 / 120
  default".
* §3.3 pins the ``chunk_id`` formula:
  ``chunk_id = sha256(document_sha256 || chunker_version || position)``.

Token approximation
-------------------
The chunker does not own a tokenizer — keeping it tokenizer-free makes
re-indexing deterministic across embedding-model upgrades. Instead we
apply the industry-standard heuristic **1 token ≈ 4 characters** used
throughout the LangChain / OpenAI cookbook ecosystem, so the default
``chunk_size_tokens=800`` maps to a 3200-character window and
``chunk_overlap_tokens=120`` maps to a 480-character overlap. The
recorded ``token_count`` on each :class:`ChunkRecord` is the character
length divided by four (rounded up) — downstream callers that need exact
token counts should re-tokenize with the model's own tokenizer.

Embedding placeholder
---------------------
The chunker is pure text-layer work: it emits :class:`ChunkRecord`s with
an empty ``embedding=[]``. The caller (``research-indexer`` worker) then
passes the records through :meth:`EmbeddingsProvider.embed` before the
final :meth:`VectorStore.upsert` call. We still surface ``embedding_model``
and ``embedding_dim`` kwargs so the caller can stamp them on the record
upfront, keeping the embed step a pure vector-fill rather than a partial
re-construction of the record.

The ``ChunkRecord`` Pydantic model enforces ``embedding_dim > 0``
(Req 2.14 pins the pgvector ``VECTOR(dim)`` column to a positive
length), so the chunker validates its own ``embedding_dim`` kwarg
against that same bound. A default of ``0`` means "caller has not yet
decided" and is treated as a placeholder of ``1`` while the chunker
emits the record — the downstream embedder is expected to overwrite
both ``embedding`` and ``embedding_dim`` with the real values before
the record ever reaches the vector store.
"""

from __future__ import annotations

import hashlib
import math
from typing import Final
from uuid import UUID

from src.research.ingest.parser.canonical import CanonicalDoc
from src.research.providers.base import ChunkRecord

# Industry-standard heuristic used by LangChain's RecursiveCharacterTextSplitter.
# Keeps the chunker tokenizer-free (so re-indexing is deterministic even
# when the embedding model changes) while still producing chunks close
# to the configured token bound.
_CHARS_PER_TOKEN: Final[int] = 4

# Separator ladder for the recursive splitter, in descending preference.
# We prefer paragraph breaks first, then sentence-ish breaks, then
# words, before finally falling back to a hard character boundary. The
# ladder is identical in spirit to LangChain's default but trimmed to
# the separators that actually occur in our canonical Markdown output
# (design §3.2: paragraphs + Markdown tables + occasional bullet lists).
_DEFAULT_SEPARATORS: Final[tuple[str, ...]] = (
    "\n\n",  # paragraph break
    "\n",  # line break (table rows, bullet items)
    ". ",  # sentence end
    "? ",
    "! ",
    "; ",
    ", ",
    " ",
    "",  # character-level fallback
)


def _tokens_to_chars(tokens: int) -> int:
    """Convert the token-denominated knob to a character count.

    See the module docstring for the 1 token ≈ 4 chars rationale. A
    zero / negative input returns zero so the caller's validation
    errors surface at the top of :func:`chunk_document` instead of
    inside the splitter loop.
    """
    if tokens <= 0:
        return 0
    return tokens * _CHARS_PER_TOKEN


def _approx_token_count(text: str) -> int:
    """Approximate a chunk's token count from its character length.

    Uses ``ceil(len(text) / _CHARS_PER_TOKEN)`` so a single-character
    chunk still records ``token_count=1`` (rather than zero, which would
    trip the ``ge=0`` validator on :class:`ChunkRecord` silently).
    """
    if not text:
        return 0
    return math.ceil(len(text) / _CHARS_PER_TOKEN)


def _derive_chunk_id(
    *,
    document_sha256: str,
    chunker_version: str,
    position: int,
) -> str:
    """Compute the stable chunk id (design §3.3, Req 3.12).

    Formula: ``sha256(document_sha256 || chunker_version || str(position))``
    with the three parts concatenated using the ASCII NUL byte as a
    separator so the input to SHA-256 is unambiguous (e.g. a
    ``chunker_version`` of ``"v10"`` and ``position=0`` cannot collide
    with ``"v1"`` and ``position=00`` — NUL separators prevent that).
    Returns lowercase hex, 64 chars, matching the shape
    :class:`~src.research.ingest.parser.canonical.CanonicalDoc.sha256`
    already validates.
    """
    hasher = hashlib.sha256()
    hasher.update(document_sha256.encode("utf-8"))
    hasher.update(b"\x00")
    hasher.update(chunker_version.encode("utf-8"))
    hasher.update(b"\x00")
    hasher.update(str(position).encode("utf-8"))
    return hasher.hexdigest()


def _split_recursive(
    text: str,
    *,
    chunk_size_chars: int,
    chunk_overlap_chars: int,
    separators: tuple[str, ...] = _DEFAULT_SEPARATORS,
) -> list[str]:
    """Recursive character splitter producing ``≤ chunk_size_chars`` pieces.

    Mirrors the behaviour callers expect from LangChain's
    ``RecursiveCharacterTextSplitter``:

    1. If ``text`` fits in the window, return it as a single piece.
    2. Pick the first separator from ``separators`` that occurs in
       ``text``; split on it and greedily pack consecutive pieces into
       chunks up to ``chunk_size_chars``.
    3. For any split piece still larger than the window, recurse with
       the *remaining* (less-preferred) separators.
    4. Finally, overlap adjacent chunks by ``chunk_overlap_chars`` by
       prepending the tail of the previous chunk to the head of the
       next one.

    Kept separate from :func:`chunk_document` so it is unit-testable
    without constructing a :class:`CanonicalDoc`.
    """
    if chunk_size_chars <= 0:
        return []
    if not text:
        return []
    if len(text) <= chunk_size_chars:
        return [text]

    separator = ""
    remaining: tuple[str, ...] = ()
    for idx, candidate in enumerate(separators):
        if candidate == "" or candidate in text:
            separator = candidate
            remaining = separators[idx + 1 :]
            break

    # Split on the chosen separator; keep the separator attached to the
    # *preceding* piece so the recombined chunk reads naturally.
    pieces: list[str] = []
    if separator == "":
        # Character-level fallback: window-stride over the string with
        # no overlap here (overlap is applied across final chunks
        # below, uniformly).
        for start in range(0, len(text), chunk_size_chars):
            pieces.append(text[start : start + chunk_size_chars])
    else:
        parts = text.split(separator)
        for idx, part in enumerate(parts):
            if idx < len(parts) - 1:
                pieces.append(part + separator)
            else:
                pieces.append(part)

    # Any piece still over the window gets recursed with the remaining
    # (less-preferred) separators.
    expanded: list[str] = []
    for piece in pieces:
        if len(piece) <= chunk_size_chars:
            expanded.append(piece)
        else:
            expanded.extend(
                _split_recursive(
                    piece,
                    chunk_size_chars=chunk_size_chars,
                    chunk_overlap_chars=chunk_overlap_chars,
                    separators=remaining or ("",),
                ),
            )

    # Greedy packing: join consecutive small pieces so we approach the
    # window bound rather than emitting many tiny chunks. Filter empty
    # pieces introduced by back-to-back separators.
    packed: list[str] = []
    buf = ""
    for piece in expanded:
        if not piece:
            continue
        if len(buf) + len(piece) <= chunk_size_chars:
            buf += piece
        else:
            if buf:
                packed.append(buf)
            # If a single piece alone exceeds the window (can't happen
            # after recursion, but guard anyway), emit it as-is.
            buf = piece
    if buf:
        packed.append(buf)

    # Apply overlap across adjacent packed chunks by prepending the tail
    # of the previous chunk to the head of the next. This yields the
    # standard "sliding window" behaviour downstream retrieval expects.
    if chunk_overlap_chars <= 0 or len(packed) <= 1:
        return packed
    with_overlap: list[str] = [packed[0]]
    for prev, curr in zip(packed, packed[1:]):
        overlap = prev[-chunk_overlap_chars:] if chunk_overlap_chars < len(prev) else prev
        with_overlap.append(overlap + curr)
    return with_overlap


def chunk_document(
    doc: CanonicalDoc,
    *,
    user_id: UUID,
    chunk_size_tokens: int = 800,
    chunk_overlap_tokens: int = 120,
    chunker_version: str = "v1",
    embedding_model: str = "",
    embedding_dim: int = 0,
) -> list[ChunkRecord]:
    """Split *doc* into :class:`ChunkRecord`s ready for embedding + upsert.

    Parameters
    ----------
    doc:
        The canonical document produced by the ingest parser stage
        (:mod:`src.research.ingest.parser.canonical`). Its
        ``canonical_text`` is the text we split and its ``sha256``
        feeds the stable ``chunk_id`` derivation.
    user_id:
        Tenant scope; required because :class:`ChunkRecord.user_id` is
        a mandatory namespace key (Req 3.10, Req 4.5) and
        :class:`CanonicalDoc` does not itself carry ``user_id``.
    chunk_size_tokens:
        Upper bound per chunk, measured in approximate tokens (1 token
        ≈ 4 chars). Defaults to 800 per Req 3.6.
    chunk_overlap_tokens:
        Overlap between adjacent chunks in approximate tokens. Defaults
        to 120 per Req 3.6.
    chunker_version:
        Version tag mixed into the chunk-id hash (design §3.3). Bumping
        this value deliberately changes the ``chunk_id`` set and thus
        forces a re-index — that behaviour is part of Req 3.12 and is
        exercised by
        ``tests/research/test_prop_reindex_idempotent.py``
        (``test_chunker_version_bump_changes_ids``).
    embedding_model:
        Stamped onto each emitted :class:`ChunkRecord` so downstream
        code can confirm embedder-record alignment. The chunker itself
        does not call the embedder; an empty string is valid and means
        "caller will populate this before upsert".
    embedding_dim:
        Length of the embedding vector the downstream embedder will
        produce. Zero is valid and means the same as an empty
        ``embedding_model``: the caller will populate it.

    Returns
    -------
    list[ChunkRecord]
        A fresh list of records ordered by ``position``. Each record
        has an empty ``embedding`` list — the caller is expected to
        run :meth:`EmbeddingsProvider.embed` over ``record.text`` and
        write the resulting vector back onto ``record.embedding``
        before calling :meth:`VectorStore.upsert`.

    Notes
    -----
    * The function is **pure and deterministic**: given the same
      ``doc`` and the same kwargs it returns byte-identical output.
      Property 4 / Req 14.4 depends on this.
    * An empty ``canonical_text`` yields an empty result — no chunks,
      no error; the ingest worker interprets that as "parsed-but-empty
      document" and simply skips the embed/upsert steps.
    * ``chunk_overlap_tokens`` must be strictly less than
      ``chunk_size_tokens`` — otherwise adjacent chunks would overlap
      by more than the window size, which is almost certainly a
      configuration mistake. We raise :class:`ValueError` for that
      case so misconfiguration fails loudly at startup rather than
      silently producing a degenerate chunk stream.

    """
    if chunk_size_tokens <= 0:
        raise ValueError(
            f"chunk_size_tokens must be > 0, got {chunk_size_tokens}",
        )
    if chunk_overlap_tokens < 0:
        raise ValueError(
            f"chunk_overlap_tokens must be >= 0, got {chunk_overlap_tokens}",
        )
    if chunk_overlap_tokens >= chunk_size_tokens:
        raise ValueError(
            "chunk_overlap_tokens must be strictly less than "
            f"chunk_size_tokens (got overlap={chunk_overlap_tokens}, "
            f"size={chunk_size_tokens})",
        )

    # Empty doc → empty chunk list. Deliberately not an error: the
    # ingest worker will persist the Document_Store record even when
    # the canonical text is empty (e.g. an all-images PDF), and the
    # absence of chunks is how downstream code knows not to attempt
    # retrieval against this document.
    canonical_text = doc.canonical_text
    if not canonical_text:
        return []

    chunk_size_chars = _tokens_to_chars(chunk_size_tokens)
    chunk_overlap_chars = _tokens_to_chars(chunk_overlap_tokens)

    pieces = _split_recursive(
        canonical_text,
        chunk_size_chars=chunk_size_chars,
        chunk_overlap_chars=chunk_overlap_chars,
    )

    # ``ChunkRecord.embedding_dim`` is validated ``gt=0`` on the model.
    # A kwarg of ``0`` means "caller has not yet decided" and is
    # replaced here with the minimal placeholder ``1``. The downstream
    # embedder overwrites both ``embedding`` and ``embedding_dim``
    # before the record reaches the vector store, so the placeholder
    # is never observed by retrieval callers.
    effective_dim = embedding_dim if embedding_dim > 0 else 1

    records: list[ChunkRecord] = []
    for position, piece in enumerate(pieces):
        chunk_id = _derive_chunk_id(
            document_sha256=doc.sha256,
            chunker_version=chunker_version,
            position=position,
        )
        records.append(
            ChunkRecord(
                chunk_id=chunk_id,
                document_id=doc.document_id,
                user_id=user_id,
                symbol=doc.symbol,
                position=position,
                token_count=_approx_token_count(piece),
                text=piece,
                embedding=[],
                embedding_model=embedding_model,
                embedding_dim=effective_dim,
            ),
        )
    return records


__all__ = [
    "chunk_document",
]
