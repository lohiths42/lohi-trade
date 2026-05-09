"""Pluggable LLM, embeddings, and vector-store providers (design §3.1).

Defines the Pydantic-contracted `LLMProvider`, `EmbeddingsProvider`, and
`VectorStore` abstractions and hosts one adapter file per concrete backend.
Adding a new provider is a single new file plus a single registration line
in `registry.py` (Req 2.12).
"""
