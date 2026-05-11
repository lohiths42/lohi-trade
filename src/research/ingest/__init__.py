"""Document ingestion pipeline (design §3.2).

Acquires filings and announcements from BSE/NSE feeds, user-upload watch
folders, and optional SEBI EDIFAR / company IR sources; normalises them to
the `CanonicalDoc` representation; deduplicates by SHA-256 content hash;
and hands chunks to `src/research/index/` for embedding. Respects each
source's `robots.txt` (Req 3.3).
"""
