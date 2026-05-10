"""Deterministic citation-integrity validator (design §3.8, §12).

Catches citation hallucinations an LLM judge might miss.

Scope
-----
For a given ``ResearchBrief`` and its run-context ``(user_id, symbol)``,
this validator asserts that **every** citation attached to the brief
carries a ``chunk_id`` that exists in the active
:class:`~src.research.providers.base.VectorStore` under the same
``(user_id, symbol)`` namespace. Any citation whose ``chunk_id`` is
unknown to the store becomes an
:class:`~src.research.validators.types.UnsupportedClaim` with
``reason="citation_mismatch"`` (design §3.7, §3.8, Req 3.11, Req 14.1).

Why this is deterministic
-------------------------
The Judge_LLM (Task 12.1, design §3.7) scores *semantic* groundedness —
does the cited chunk actually support the claim? This validator asks
the far simpler, purely mechanical question: **does the cited
``chunk_id`` resolve at all?** Forged chunk_ids are a classic
hallucination failure mode (the model invents a plausible-looking hex
string) and a deterministic set-membership check catches them without
needing a second LLM pass. Deterministic checks also survive offline
mode (design §11.4) where the LLM judge is unavailable.

Inputs accepted
---------------
Because the full ``ResearchBrief`` Pydantic model lands later (Task
13.8), the validator duck-types on a minimal **citations accessor** —
the same strategy the numeric validator (Task 11.1) uses for brief
section text:

* ``list | tuple`` of citation-like objects — accepted directly.
* Any object exposing ``.citations`` (a ``list``-like) — read via
  ``getattr(brief, "citations", None)``.
* A ``Mapping`` carrying ``"citations"`` — looked up via ``__getitem__``.

Each citation-like object must expose a ``.chunk_id`` string. Other
fields (``document_id``, ``source_url``, ``start_offset``,
``end_offset``) are irrelevant to this validator and are ignored. This
keeps the module from taking a hard dependency on the Pydantic
``Citation`` model that Task 13.8 will introduce — when that model
lands, this validator accepts it unchanged.

How "exists in the active VectorStore" is checked
-------------------------------------------------
The :class:`VectorStore` protocol (Task 2.1) exposes ``upsert``,
``similarity_search``, ``delete_by_filter``, and ``count``. None of
them offer a direct ``get_by_id`` lookup. The cleanest API that works
across every shipped adapter (Chroma, pgvector, Qdrant, LanceDB) is to
**enumerate** the namespace:

1. Build a :class:`RetrievalFilter` pinned to the run's
   ``(user_id, symbol)`` — exactly the namespace that any legitimately
   cited chunk must live inside (Req 3.10).
2. Issue a ``similarity_search`` with ``k = count(filter)`` and a
   ``query_vec`` of zeros whose length matches whatever the store's
   chunks expect (discovered via a single-hit probe call).
3. Collect every returned ``ChunkHit.chunk.chunk_id`` into a set —
   that set is the ground truth of "known" chunk_ids for the run's
   namespace.
4. For each brief-side citation, set-membership test the
   ``chunk_id``. A miss is a
   :class:`UnsupportedClaim` with ``reason="citation_mismatch"``
   (Req 14.1).

Notes on the enumeration approach:

* ``count()`` gives the exact namespace size, so ``k`` is not a
  lossy top-k cut — every chunk in the namespace makes it into the
  known-ids set. A fresh namespace (count == 0) short-circuits the
  search and every citation fails, which is the right outcome.
* The zero query vector is harmless under the protocol's contract:
  ``FakeVectorStore`` explicitly guards zero-norm inputs (score 0.0),
  and every production adapter returns the top-``k`` matches ordered
  by score — **which** ``k`` rows come back doesn't matter here
  because we only read ``chunk_id``.
* ``min_score`` on the filter is deliberately left unset (``None``)
  so the similarity floor (design §3.3, Req 16.24) does not filter
  out legitimately indexed chunks that happen to score low against
  the probe vector.
* Probing the embedding length is delegated to an optional caller-
  supplied hint (``embedding_dim``). If the hint is missing, the
  validator issues a single-row ``similarity_search`` with a dummy
  1-dim vector to read the first matching chunk's ``embedding_dim``,
  then retries with the right-sized zero vector. Stores whose
  cosine implementation short-circuits on length-mismatch (every
  shipped adapter, per the ``FakeVectorStore`` reference
  implementation) simply return no hits on the probe; that is
  treated as "namespace empty" and every citation fails cleanly.

Satisfies
---------
* Req 3.11 — every Citation SHALL resolve to an existing chunk in the
  Vector_Store at the time of generation.
* Req 14.1 — property-level statement of Req 3.11.
* Design §3.8 — deterministic citation-integrity validator emitting
  ``UnsupportedClaim(reason="citation_mismatch")``.
* Design §12 — hallucination defences layer: catches forged chunk_ids
  before the brief is shown.

Design references
-----------------
* §3.7 — Judge_LLM ``UnsupportedClaim`` schema (canonical definition).
* §3.8 — Validators shipped — ``citation_validator.py``.
* §12 — Hallucination defences — deterministic citation-integrity
  validator over every Research_Brief.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Protocol, runtime_checkable
from uuid import UUID

from src.research.providers.base import RetrievalFilter, VectorStore
from src.research.validators.types import UnsupportedClaim

__all__ = [
    "CitationValidator",
    "validate_citations",
]


# --------------------------------------------------------------------------- #
# Duck-typed citation protocol                                                #
# --------------------------------------------------------------------------- #


@runtime_checkable
class _CitationLike(Protocol):
    """Minimal duck-typed citation — anything with ``.chunk_id`` satisfies.

    The full ``Citation`` Pydantic model (design §4.2) lands in Task
    13.8. Until then the validator reads only the one field it needs;
    this keeps the module from taking a premature hard dependency on
    a model that is still being specified.
    """

    chunk_id: str


# --------------------------------------------------------------------------- #
# Citations accessor                                                          #
# --------------------------------------------------------------------------- #


def _coerce_citations(
    brief: Iterable[_CitationLike] | Mapping[str, object] | object,
) -> list[_CitationLike]:
    """Normalise accepted brief-shaped inputs into ``[citation, ...]``.

    Accepts three shapes so callers can pass whichever is handiest:

    * A plain ``list``/``tuple`` of citation-like objects — returned
      verbatim.
    * A :class:`Mapping` exposing ``"citations"`` — read via
      ``__getitem__``.
    * Any object exposing ``.citations`` — read via ``getattr``.

    Returns an empty list when the brief carries no citations (e.g. a
    ``partial=true`` run whose only sections are ``no_data`` agent
    outputs, Req 1.6) so the validator never raises on a legitimately
    citation-less brief. An empty list means "no citations to check"
    — which, per the validator's contract, yields zero violations.
    """
    # List / tuple of citation-like objects — accept verbatim. We
    # explicitly sidestep ``str`` even though it is iterable, because
    # a bare string would loop character-by-character and then fail
    # ``.chunk_id`` attribute access in the main loop below.
    if isinstance(brief, (list, tuple)):
        return list(brief)

    # Mapping with a ``"citations"`` key.
    if isinstance(brief, Mapping):
        raw = brief.get("citations")
        if raw is None:
            return []
        if isinstance(raw, (list, tuple)):
            return list(raw)
        # Any other iterable shape — materialise once so we don't
        # consume a single-pass generator the caller may need again.
        return list(raw)  # type: ignore[arg-type]

    # Object exposing ``.citations``.
    raw = getattr(brief, "citations", None)
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return list(raw)
    # Treat any other iterable shape identically to the Mapping path.
    return list(raw)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Known-chunk-id enumeration                                                  #
# --------------------------------------------------------------------------- #


# Arbitrary small default for the embedding-probe. The validator only
# uses the probe to discover the real dim — the 1-dim vector is never
# compared for relevance.
_PROBE_DIM: int = 1


async def _known_chunk_ids(
    vector_store: VectorStore,
    *,
    user_id: UUID,
    symbol: str,
    embedding_dim: int | None,
) -> set[str]:
    """Return the set of ``chunk_id``\\s indexed under ``(user_id, symbol)``.

    Implementation details are spelled out in the module docstring;
    in short:

    1. :meth:`VectorStore.count` gives the namespace size.
    2. :meth:`VectorStore.similarity_search` with ``k == namespace size``
       and a zero query vector enumerates every chunk in order.
    3. We read only ``hit.chunk.chunk_id``.

    Parameters
    ----------
    vector_store:
        The active :class:`VectorStore` for the Research_Run.
    user_id, symbol:
        The run context — the namespace filter (Req 3.10).
    embedding_dim:
        Optional hint. When supplied, the zero query vector is sized
        directly; when ``None``, the function issues a tiny probe
        search to learn the dim from the first returned chunk.

    Returns
    -------
    set[str]
        Every known ``chunk_id`` under the namespace. Empty when the
        namespace is empty.

    """
    namespace_filter = RetrievalFilter(user_id=user_id, symbol=symbol)
    namespace_size = await vector_store.count(namespace_filter)
    if namespace_size <= 0:
        # Empty namespace — every citation attached to the brief will
        # fail (as it should: a citation pointing into an empty
        # namespace is by definition a citation_mismatch).
        return set()

    # Discover the embedding dim. The run-scoped ``embedding_dim``
    # argument is the fast path; a probe call is the fallback.
    dim = embedding_dim
    if dim is None or dim <= 0:
        # Single-hit probe with a harmless 1-dim vector. A store whose
        # cosine implementation rejects length-mismatched vectors
        # returns an empty hit list here (the FakeVectorStore
        # reference behaviour); that is not a failure — it just means
        # the probe learned nothing, so we fall back to a default
        # guess of the namespace's first chunk's declared dim by
        # reading a larger search. We model that by retrying with a
        # 384-long vector — the default ``sentence-transformers`` dim
        # (Task 2.11), which every shipped adapter supports natively.
        probe_hits = await vector_store.similarity_search(
            [0.0] * _PROBE_DIM,
            filter=namespace_filter,
            k=1,
        )
        if probe_hits:
            dim = probe_hits[0].chunk.embedding_dim
        else:
            # Fall back to the default project embedding dim. 384 is
            # the ``BAAI/bge-small-en-v1.5`` vector length (design
            # §3.3, Req 2.5); stores serving a different model will
            # simply return zero hits below, which we then treat the
            # same way the empty namespace above is treated.
            dim = 384

    # Zero vector sized to match the stored embeddings. Score ordering
    # is irrelevant to this validator; we only read ``chunk_id``.
    query_vec = [0.0] * dim
    hits = await vector_store.similarity_search(
        query_vec,
        filter=namespace_filter,
        k=namespace_size,
    )

    known: set[str] = {hit.chunk.chunk_id for hit in hits}

    # If the enumeration under-returned relative to ``count`` (e.g.
    # the adapter's cosine rejected the length-mismatched query when
    # the namespace mixes embedding models), retry once with the
    # commonly-used 384-dim default — this is cheap and has no
    # correctness cost because we still only read ``chunk_id``.
    if len(known) < namespace_size and dim != 384:
        retry_hits = await vector_store.similarity_search(
            [0.0] * 384,
            filter=namespace_filter,
            k=namespace_size,
        )
        known.update(hit.chunk.chunk_id for hit in retry_hits)

    return known


# --------------------------------------------------------------------------- #
# Validator                                                                   #
# --------------------------------------------------------------------------- #


class CitationValidator:
    """Deterministic citation-integrity validator (design §3.8, Req 14.1).

    Stateless beyond its :class:`VectorStore` reference, so a single
    instance can be shared across concurrent runs as long as the
    store supports concurrent reads (every shipped adapter does).

    Parameters
    ----------
    vector_store:
        The active :class:`VectorStore` for the run. Passed directly
        rather than resolved from config so the Orchestrator can
        inject whatever the registry produced at boot (design §8).
    embedding_dim:
        Optional hint forwarded to :func:`_known_chunk_ids`. Set it
        when the caller already knows the run's embedding dim
        (virtually always true in production — the Orchestrator holds
        the :class:`EmbeddingsProvider` reference and therefore knows
        ``dim``); leave it ``None`` in tests that build the store by
        hand.

    """

    def __init__(
        self,
        vector_store: VectorStore,
        *,
        embedding_dim: int | None = None,
    ) -> None:
        self._vector_store = vector_store
        self._embedding_dim = embedding_dim

    async def validate(
        self,
        *,
        brief: Iterable[_CitationLike] | Mapping[str, object] | object,
        user_id: UUID,
        symbol: str,
    ) -> list[UnsupportedClaim]:
        """Validate ``brief`` citations against the active store.

        Parameters
        ----------
        brief:
            Either a ``list`` / ``tuple`` of citation-like objects, a
            :class:`Mapping` carrying a ``"citations"`` key, or any
            object exposing ``.citations``. See
            :func:`_coerce_citations` for the full acceptance shape.
        user_id, symbol:
            The run context — every citation must resolve inside the
            ``(user_id, symbol)`` namespace (Req 3.10).

        Returns
        -------
        list[UnsupportedClaim]
            One entry per citation whose ``chunk_id`` is unknown to the
            active store under the run's namespace, each tagged with
            ``reason="citation_mismatch"``. Empty when every citation
            resolves — the common case for well-synthesised briefs.

        Behavioural notes
        -----------------
        * Citations are checked in the order they appear on the brief,
          so violation order is stable across runs — useful when
          diffing test snapshots or feeding violations back into the
          re-synthesis loop (design §11.2).
        * A brief carrying zero citations returns zero violations
          (vacuous pass). The numeric validator catches
          claims-without-citations via a separate pathway; this
          validator's sole contract is ``chunk_id`` existence.
        * Empty / whitespace ``chunk_id`` strings are treated the same
          as missing citations and emit a violation — they cannot
          possibly resolve in the store.

        """
        citations = _coerce_citations(brief)
        if not citations:
            return []

        known_ids = await _known_chunk_ids(
            self._vector_store,
            user_id=user_id,
            symbol=symbol,
            embedding_dim=self._embedding_dim,
        )

        violations: list[UnsupportedClaim] = []
        for citation in citations:
            chunk_id = getattr(citation, "chunk_id", None)
            # Missing, wrong-type, or whitespace-only ``chunk_id`` is a
            # violation: the store cannot possibly know about a
            # non-existent or empty id.
            if not isinstance(chunk_id, str) or not chunk_id.strip():
                violations.append(_mismatch_claim(chunk_id))
                continue
            if chunk_id in known_ids:
                continue
            violations.append(_mismatch_claim(chunk_id))
        return violations


async def validate_citations(
    *,
    vector_store: VectorStore,
    brief: Iterable[_CitationLike] | Mapping[str, object] | object,
    user_id: UUID,
    symbol: str,
    embedding_dim: int | None = None,
) -> list[UnsupportedClaim]:
    """Module-level convenience wrapper around :class:`CitationValidator`.

    Intended for call sites that do not need a persistent validator
    instance — the Orchestrator's per-run citation check (design §3.5,
    §12) and the offline rule-based judge (design §11.4). Equivalent
    to::

        CitationValidator(vector_store, embedding_dim=embedding_dim).validate(
            brief=brief, user_id=user_id, symbol=symbol,
        )
    """
    return await CitationValidator(
        vector_store,
        embedding_dim=embedding_dim,
    ).validate(brief=brief, user_id=user_id, symbol=symbol)


# --------------------------------------------------------------------------- #
# Internals                                                                   #
# --------------------------------------------------------------------------- #


# The :class:`UnsupportedClaim` contract requires a non-empty
# ``section`` and a non-empty ``claim_text`` plus strictly positive
# ``end_offset`` greater than ``start_offset`` (see
# ``types.UnsupportedClaim.model_post_init``). The citation validator
# does not track section provenance (a citation can be shared across
# sections; carrying the section here would require callers to supply
# a ``citation -> section`` map that doesn't exist upstream yet).
# Until Task 13.8 wires a richer model, we use a synthetic section
# marker that downstream (re-synthesis loop, design §11.2) knows how
# to interpret.
_CITATION_SECTION_MARKER: str = "citations"


def _mismatch_claim(chunk_id: object) -> UnsupportedClaim:
    """Build the canonical ``citation_mismatch`` ``UnsupportedClaim``.

    ``claim_text`` carries the (stringified) offending ``chunk_id`` so
    the re-synthesis loop (design §11.2) can show the model exactly
    which id failed. Offsets are synthetic (``0 .. len(claim_text)``)
    — the citation validator does not know where in the brief body
    the citation was rendered, and :class:`UnsupportedClaim` enforces
    ``end_offset > start_offset`` strictly, so we anchor to the claim
    text's own length.
    """
    # Stringify defensively — missing / wrong-type chunk_ids arrive
    # here as ``None`` or other non-str values (see
    # :meth:`CitationValidator.validate`). Empty-string chunk_ids
    # become ``"<missing>"`` so ``claim_text`` stays non-empty, which
    # the ``UnsupportedClaim`` model requires (``min_length=1``).
    text = str(chunk_id) if chunk_id else "<missing>"
    if not text.strip():
        text = "<missing>"
    return UnsupportedClaim(
        section=_CITATION_SECTION_MARKER,
        claim_text=text,
        start_offset=0,
        end_offset=len(text),
        reason="citation_mismatch",
    )
