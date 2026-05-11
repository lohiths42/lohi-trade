"""Embeddings, hybrid retrieval, and reranking (design §3.3).

Turns `CanonicalDoc` chunks into embedded, `(user_id, symbol)`-namespaced
vectors; exposes a hybrid BM25 + dense retriever with an optional
cross-encoder reranker; and guarantees idempotent re-indexing via stable
`chunk_id = sha256(document_sha256 || chunker_version || position)`
(Req 3.7–3.12).
"""
