"""Working, Semantic, and Episodic memory layers (design §3.4).

- Working_Memory: Redis sliding window + running summary per conversation.
- Semantic_Memory: Postgres + vectors, per-user summaries and preferences.
- Episodic_Memory: Postgres timeline per `(user_id, symbol)`.

All queries are strictly user-scoped and enforced at the Postgres RLS
layer (Req 4.5, 4.6). Exposes a `memory.forget(user_id, scope)` operation
with audit logging (Req 4.8, 4.9).
"""
