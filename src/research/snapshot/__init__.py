"""Per-symbol precomputed `Research_Brief` cache (design §3.10).

Precomputes, caches, and invalidates per-`(user_id, symbol)` Snapshots for
watchlist symbols. New indexed documents, Commander bias events, and
high-impact sentiment events invalidate the matching Snapshot, which is
regenerated after a debounce window (Req 11.1–11.6). Fresh Snapshots are
served directly and bypass Sub_Agent fan-out (Req 5.5).
"""
