"""Redis caches and latency-budget plumbing (design §3.11).

Hosts the three Redis caches named in Req 5.6–5.8 — embedding cache,
retrieval cache, and LLM response cache — plus the `research:latency_budget`
pubsub channel that carries `latency_budget_exceeded` events (Req 5.9).
Streaming runs bypass the LLM response cache.
"""
