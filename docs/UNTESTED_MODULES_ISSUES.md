# Untested Modules — Triage List

This file lists large modules with no unit tests identified during the test run. Use these entries to create GitHub issues and prioritize tests.

## High Priority (critical runtime)
- `src/state/database.py` — database connection, migrations, backups
- `src/execution/oms.py` — order management system logic
- `src/ingestion/market_data_collector.py` — live market feeds, parsing
- `src/research/providers/llm/nvidia_nim.py` — provider adapter (network behaviour)

## Medium Priority
- `src/research/agents/orchestrator.py` — complex orchestration
- `src/research/workers/snapshotter.py` — snapshot persistence
- `src/soldier/indicator_engine.py` — signal computations

## Low Priority
- UI modules (`src/ui/*`)
- docs and CLI helpers

## Suggested first tests
1. `tests/test_state_database_smoke.py` — import and validate config-based DB URL parsing
2. `tests/test_execution_oms_smoke.py` — instantiate OMS with fake broker interface
3. `tests/test_research_provider_nim_unit.py` — ensure payload building and auth error handling without network
