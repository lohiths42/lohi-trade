"""Content-hash dedup for the ingestion pipeline (Req 3.5, design §3.2).

Two public entry points:

* :func:`compute_document_sha256` — deterministic SHA-256 over a
  document's canonical text plus its metadata. The ingest worker stores
  this value on :class:`~backend-gateway.app.models.research.document.ResearchDocument.sha256`,
  and the pretty-printer carries it end-to-end on
  :class:`~src.research.ingest.parser.canonical.CanonicalDoc.sha256`.
* :func:`is_duplicate` — async lookup against ``research_documents``
  that lets the ingest worker skip parse + embed when the same
  ``(user_id, sha256)`` is already persisted (Req 3.5).

Requirements covered
--------------------
* **Req 3.5** — "IF a Document_Store record with the same content hash
  already exists, THEN THE Lohi_Research SHALL skip re-parsing and
  re-embedding for that document."

Design references
-----------------
* :file:`.kiro/specs/lohi-research-dashboard/design.md` §3.2 names this
  module — "``dedup.py`` — SHA-256 content hash, idempotent re-ingestion
  (Req 3.5)".
* :file:`backend-gateway/alembic/versions/002_research_tables.py`
  defines the unique ``(user_id, sha256)`` index this helper relies on;
  the ORM model in :mod:`backend-gateway.app.models.research.document`
  mirrors that index.

RLS contract
------------
:func:`is_duplicate` receives an ``asyncpg.Connection`` that **must
already have ``app.user_id`` set** for the current transaction (see
:mod:`backend-gateway.app.services.research.rls`). This is deliberate:

* The research-indexer worker runs outside the FastAPI request lifecycle
  and therefore outside the gateway's JWT middleware, which is the code
  path that normally sets ``app.user_id``. The worker must set it
  itself before any query — typically via
  :func:`backend-gateway.app.services.research.rls.rls_connection` —
  and the caller is the only place that knows *which* user owns the
  document being ingested.
* Pushing the ``app.user_id`` plumbing down into :func:`is_duplicate`
  would mean a second ``set_config`` per call, and because the helper
  uses ``is_local=true`` scoping, multiple set-config calls inside the
  same transaction are redundant at best and order-sensitive at worst.

Hash stability
--------------
The hash input is the concatenation of the canonical text and a
deterministic JSON serialisation of the metadata dict. JSON is serialised
with ``sort_keys=True`` and ``ensure_ascii=False`` so:

* Two parsers that emit the same metadata in different key order produce
  the same hash.
* Unicode characters in metadata (e.g. company names with diacritics)
  round-trip losslessly without escape-sequence drift.

Non-JSON-serialisable values (datetimes, UUIDs, enums) are stringified
via :func:`str` before hashing so the helper cannot raise on metadata
shapes the canonical parser is happy to accept. Downstream callers that
need strict typing on metadata should validate before calling this
function — :class:`CanonicalDoc.metadata` is an ``Any`` dict and
deliberately permissive.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:  # pragma: no cover - typing only
    import asyncpg


def compute_document_sha256(canonical_text: str, metadata: dict[str, Any]) -> str:
    """Return the stable 64-char lowercase hex SHA-256 for a document.

    The hash is taken over the UTF-8 encoding of:

    .. code-block:: text

        canonical_text + "\\n" + json.dumps(metadata, sort_keys=True, …)

    A literal newline separates the two parts so a pathological
    metadata payload cannot masquerade as part of the canonical text
    (preventing a collision where two different ``(canonical_text,
    metadata)`` pairs would hash to the same value by virtue of sharing
    the concatenation boundary).

    Parameters
    ----------
    canonical_text:
        The normalised Markdown body produced by the parser stage —
        the value stored in
        :class:`~src.research.ingest.parser.canonical.CanonicalDoc.canonical_text`.
    metadata:
        Free-form parser metadata (page count, parser name, source
        filename, etc.). Keys are sorted before serialisation so
        dictionaries that differ only by key-order hash identically.
        Non-JSON-serialisable values are stringified via :func:`str`
        via a custom ``default=`` callback rather than raising — this
        keeps the dedup layer tolerant of the full
        :class:`CanonicalDoc.metadata` contract.

    Returns
    -------
    str
        64-character lowercase hex string, matching the shape
        :class:`CanonicalDoc.sha256` validates.

    Notes
    -----
    * This function is **pure** — no I/O, no clock reads, no random
      sources. Given the same inputs it returns the same hex string on
      every call, on every Python version, on every platform. Req 3.5
      and Req 3.12 both depend on this.
    """
    # json.dumps with sort_keys=True gives a canonical ordering; the
    # default=str fallback handles datetimes, UUIDs, and enum values
    # that CanonicalDoc.metadata is allowed to carry even though they
    # are not natively JSON-serialisable.
    metadata_blob = json.dumps(
        metadata,
        sort_keys=True,
        ensure_ascii=False,
        default=str,
        separators=(",", ":"),
    )
    hasher = hashlib.sha256()
    hasher.update(canonical_text.encode("utf-8"))
    # The literal newline byte separates the two parts unambiguously;
    # see the module docstring for why.
    hasher.update(b"\n")
    hasher.update(metadata_blob.encode("utf-8"))
    return hasher.hexdigest()


async def is_duplicate(
    conn: "asyncpg.Connection",
    user_id: UUID,
    sha256: str,
) -> bool:
    """Return True iff ``research_documents`` already has ``(user_id, sha256)``.

    The ingest worker calls this helper **before** parsing and embedding
    a fetched document. On a hit, the worker logs a skip and moves on;
    on a miss, it proceeds with the full parse → chunk → embed → upsert
    pipeline (Req 3.5).

    Parameters
    ----------
    conn:
        An asyncpg connection that **must already have** ``app.user_id``
        set for the current transaction — typically acquired via
        :func:`backend-gateway.app.services.research.rls.rls_connection`.
        The query scopes by ``user_id`` explicitly *in addition to*
        relying on RLS, so the tenant isolation holds even if the
        caller forgot to engage RLS: the explicit predicate is the
        belt-and-braces layer, RLS is the defense in depth.
    user_id:
        The tenant who owns the document. Must match the
        ``app.user_id`` already set on the connection; passing a
        different UUID would produce a query that RLS filters to
        zero rows and this function would return ``False`` — a silent
        correctness failure. Callers that go through
        :func:`rls_connection(pool, user_id)` are safe by
        construction.
    sha256:
        The 64-char lowercase hex hash produced by
        :func:`compute_document_sha256`.

    Returns
    -------
    bool
        ``True`` when a row with this ``(user_id, sha256)`` pair exists,
        ``False`` otherwise.

    Notes
    -----
    * The underlying table has a ``UNIQUE (user_id, sha256)`` index
      (see ``research_documents_user_id_sha256_key`` in
      :file:`002_research_tables.py`) so this lookup is O(log n).
    * We use ``SELECT 1 … LIMIT 1`` rather than ``COUNT(*)`` so the
      planner can short-circuit on the first matching row — important
      once the table accumulates many documents for the same symbol.
    """
    row = await conn.fetchrow(
        """
        SELECT 1
        FROM research_documents
        WHERE user_id = $1 AND sha256 = $2
        LIMIT 1
        """,
        user_id,
        sha256,
    )
    return row is not None


__all__ = [
    "compute_document_sha256",
    "is_duplicate",
]
