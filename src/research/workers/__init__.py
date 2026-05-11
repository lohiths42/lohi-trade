"""Long-running worker processes for Lohi-Research (design §2.2).

Hosts the three new runtime roles started by `start-research.sh`:

- `research-orchestrator`: consumes `research:runs` and emits
  `research:partials`.
- `research-indexer`: polls BSE/NSE feeds and the user-upload watch folder,
  publishing to `research:index_events`.
- `research-snapshotter`: consumes `research:snapshot_invalidations` plus
  Commander bias events and debounces Snapshot regeneration.
"""
