"""Built-in Vector_Store adapters (design §3.1).

Each module implements the `VectorStore` protocol for a concrete backend:
Chroma (default for `Persona_Self_Hosted`, embedded on-disk), pgvector
(default for `Persona_Cloud_SaaS`, reuses the existing Postgres), plus
Qdrant and LanceDB as optional alternates. The actual backend is selected
at startup by the auto-selection logic in `providers.registry` (Req 2.13–
2.15).
"""
