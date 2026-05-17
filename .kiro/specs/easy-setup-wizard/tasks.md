# Implementation Plan: Easy Setup Wizard

## Overview

This plan implements the Easy Setup Wizard feature in dependency order: backend services first (pure logic, no UI dependency), then frontend components (consume backend APIs), then the bootstrap script and README. Property-based tests validate correctness properties from the design document using Hypothesis (Python) and fast-check (TypeScript).

## Tasks

- [-] 1. Implement Service Registry
  - [x] 1.1 Create `backend-gateway/app/services/service_registry.py` with `ServiceRegistry` class
    - Define `ServiceStatus` enum (CONFIGURED, UNCONFIGURED, SKIPPED, ERROR)
    - Define `CredentialGroup` dataclass with all fields (group_id, name, description, required, env_file, credential_keys, validation_patterns, documentation_url, tooltip_hints, features_dependent)
    - Define static `CREDENTIAL_GROUPS` list with all 6 groups (nvidia_nim, nubra, broker_shoonya, telegram, ollama, broker_angelone)
    - Define `FEATURE_DEPENDENCIES` map with OR-logic (`|` operator)
    - Implement `__init__`, `_load`, `_save`, `get_status`, `set_status`, `get_all_statuses`, `get_available_features`, `is_feature_available`
    - Create initial `data/service_registry.json` template
    - _Requirements: 3.4, 4.1, 4.6_

  - [x] 1.2 Write property test for service registry state round-trip
    - **Property 2: Service registry state round-trip**
    - Generate random registry states (mapping of group_ids to ServiceStatus values), serialize to JSON, deserialize back, assert equivalence
    - **Validates: Requirements 3.4**

  - [x] 1.3 Write property test for feature availability correctness
    - **Property 4: Feature availability correctness**
    - Generate random subsets of configured services, compute feature availability map, assert features are available iff at least one dependency group is configured
    - **Validates: Requirements 4.1**

- [-] 2. Implement Credential Store
  - [x] 2.1 Create `backend-gateway/app/services/credential_store.py` with `CredentialStore` class
    - Implement `__init__` with repo_root, env_path, env_research_path
    - Implement `write_credentials(group_id, credentials)` — determine target file from group definition, update/append key=value pairs
    - Implement `read_credentials(group_id)` — parse .env file, return dict of current values for group's keys
    - Implement `clear_credentials(group_id)` — blank out or remove keys for a group
    - Implement `ensure_gitignore()` — check and add .env entries to .gitignore if missing
    - Implement `set_file_permissions()` — chmod 600 on Unix
    - Use atomic write pattern (write to temp file, then rename) to prevent corruption
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [x] 2.2 Write property test for credential persistence round-trip
    - **Property 6: Credential persistence round-trip**
    - Generate random valid key-value pairs (valid env var names, non-empty string values), write to temp .env file, read back, assert equivalence
    - **Validates: Requirements 5.1**

  - [x] 2.3 Write property test for credential validation correctness
    - **Property 1: Credential validation correctness**
    - Generate random strings, validate against each group's regex patterns, assert validator returns error iff value doesn't match pattern (including empty strings for required fields)
    - **Validates: Requirements 2.4**

- [ ] 3. Implement Connection Tester
  - [x] 3.1 Create `backend-gateway/app/services/connection_tester.py` with `ConnectionTester` class
    - Implement `test_nvidia_nim(api_key)` — GET to NVIDIA models endpoint with Bearer token, 10s timeout
    - Implement `test_nubra(phone, mpin, totp_secret)` — attempt login handshake
    - Implement `test_broker_shoonya(api_key, client_id)` — validate Shoonya credentials
    - Implement `test_telegram(bot_token)` — GET to Telegram getMe endpoint
    - Implement `test_ollama()` — GET to localhost:11434/api/tags
    - Return `TestResult` with success, response_time_ms, error, suggestion fields
    - Handle timeouts, auth failures, network errors with appropriate error messages
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

- [ ] 4. Implement Setup Service
  - [x] 4.1 Create `backend-gateway/app/services/setup_service.py` with `SetupService` class
    - Implement `__init__` with CredentialStore and ServiceRegistry dependencies
    - Implement `submit_credentials(group_id, credentials)` — validate format using regex patterns, write to .env via CredentialStore, update registry status
    - Implement `test_connection(group_id)` — read stored credentials, call appropriate ConnectionTester method, return TestResult
    - Implement `skip_group(group_id)` — mark as SKIPPED in registry
    - Implement `reset_group(group_id)` — clear credentials, mark as UNCONFIGURED
    - Implement `get_status()` — return SetupStatusResponse with all service statuses
    - Implement `complete_setup()` — mark setup_complete=True in registry with timestamp
    - Implement rollback logic: if connection test fails after credential update, retain previous value
    - _Requirements: 2.4, 3.1, 3.4, 6.1, 8.3, 8.5, 8.6_

  - [x] 4.2 Write property test for failed reconnection rollback
    - **Property 7: Failed reconnection rollback**
    - Generate initial credentials, write them, simulate a credential update followed by a connection test failure, assert original credentials are retained
    - **Validates: Requirements 8.5**

- [ ] 5. Implement Setup Router and wire backend
  - [x] 5.1 Create `backend-gateway/app/routers/setup.py` with FastAPI router
    - Define Pydantic models: `CredentialSubmission`, `TestResult`, `ServiceStatus`, `SetupStatusResponse`
    - Implement `require_localhost` dependency (reject non-loopback IPs)
    - Implement `GET /setup/status` — returns current setup state
    - Implement `POST /setup/credentials/{group_id}` — accepts and validates credentials
    - Implement `POST /setup/test/{group_id}` — triggers connection test
    - Implement `POST /setup/skip/{group_id}` — marks group as skipped
    - Implement `POST /setup/complete` — finalizes setup
    - Implement `POST /setup/reset/{group_id}` — clears group credentials
    - Implement `GET /health/services` — returns service health status for all groups
    - _Requirements: 4.6, 5.5, 5.6, 6.1_

  - [x] 5.2 Register setup router in `backend-gateway/app/main.py`
    - Import and include setup router with prefix `/api` and tags `["setup"]`
    - Initialize SetupService, CredentialStore, ServiceRegistry as app-level dependencies
    - Ensure setup endpoints are excluded from JWT auth dependencies
    - _Requirements: 5.5_

  - [x] 5.3 Write property test for health endpoint completeness
    - **Property 5: Health endpoint completeness**
    - Generate random service registry states, call get_status(), assert response contains an entry for every registered service with correct status and features_affected list
    - **Validates: Requirements 4.6**

  - [x] 5.4 Write unit tests for setup router
    - Test localhost-only guard rejects non-loopback requests
    - Test credential submission with valid/invalid formats
    - Test skip flow updates registry correctly
    - Test complete endpoint sets setup_complete flag
    - _Requirements: 5.5, 2.4, 3.1_

- [x] 6. Checkpoint — Backend verification
  - Ensure all backend tests pass, ask the user if questions arise.

- [ ] 7. Implement frontend setup store
  - [x] 7.1 Create `Lohi-TRADE Web App Design/src/stores/setup-store.ts` with Zustand store
    - Define `SetupState` interface (services, currentStep, setupComplete, loading, error)
    - Define `SetupActions` interface (fetchStatus, submitCredentials, testConnection, skipGroup, resetGroup, completeSetup)
    - Implement API calls to backend setup endpoints using existing api-client pattern
    - Handle loading states and error responses
    - _Requirements: 3.4, 3.5_

  - [x] 7.2 Create `Lohi-TRADE Web App Design/src/lib/setup-types.ts` with shared TypeScript types
    - Define `CredentialGroupDef`, `ServiceStatus`, `TestResult`, `SetupStatusResponse` types
    - Define `CREDENTIAL_GROUPS` constant array mirroring backend definitions (for UI rendering)
    - _Requirements: 2.1, 2.2_

- [ ] 8. Implement frontend wizard components
  - [x] 8.1 Create `Lohi-TRADE Web App Design/src/components/setup/CredentialInput.tsx`
    - Masked input with reveal toggle (eye icon button)
    - Tooltip hint on hover/focus
    - Inline validation error display
    - Pattern-based client-side validation
    - Accessible: proper labels, aria attributes, focus management
    - _Requirements: 2.3, 2.6_

  - [x] 8.2 Create `Lohi-TRADE Web App Design/src/components/setup/CredentialGroupStep.tsx`
    - Render service name, description (2-3 sentences), documentation link
    - Render CredentialInput for each credential key in the group
    - "Submit" button to save credentials
    - "Test Connection" button with loading spinner and result display (green checkmark / red error)
    - "Skip for now" button for optional groups
    - Show required/optional badge
    - _Requirements: 2.1, 2.2, 2.4, 2.5, 3.1, 6.1, 6.2, 6.3, 6.6_

  - [x] 8.3 Create `Lohi-TRADE Web App Design/src/components/setup/SetupSummary.tsx`
    - Display all configured services with green status
    - Display all skipped services with amber status and affected features list
    - "Complete Setup" button to finalize
    - Link to configure skipped services later
    - _Requirements: 3.6_

  - [x] 8.4 Create `Lohi-TRADE Web App Design/src/components/setup/ServiceStatusBanner.tsx`
    - Inline banner for pages with unconfigured service dependencies
    - Shows which service is needed and link to `/settings/integrations`
    - Dismissible but re-appears on page reload
    - _Requirements: 4.2, 4.3_

  - [x] 8.5 Write property test for service status rendering completeness (frontend)
    - **Property 3: Service status rendering completeness**
    - Use fast-check to generate random service registry states, render SetupSummary, assert every registered group appears with correct status
    - **Validates: Requirements 3.6, 8.2**

  - [x] 8.6 Write property test for feature availability correctness (frontend)
    - **Property 4: Feature availability correctness (frontend)**
    - Use fast-check to generate random configured subsets, compute feature availability, assert features available iff dependency satisfied
    - **Validates: Requirements 4.1**

- [ ] 9. Implement IntegrationsWizardPage and routing
  - [x] 9.1 Create `Lohi-TRADE Web App Design/src/pages/IntegrationsWizardPage.tsx`
    - Accept `mode` prop: 'first-run' | 'settings'
    - Step-by-step flow through credential groups (stepper UI)
    - Fetch initial status from backend on mount
    - Navigate between steps, track progress
    - Final step renders SetupSummary
    - In 'settings' mode: show all groups with current status, allow re-configuration
    - Handle Ollama alternative suggestion when NVIDIA NIM is skipped
    - _Requirements: 2.1, 3.2, 3.3, 3.5, 8.1, 8.2_

  - [x] 9.2 Add routes in `Lohi-TRADE Web App Design/src/App.tsx`
    - Add `/setup/integrations` route (no auth required) → IntegrationsWizardPage mode="first-run"
    - Add `/settings/integrations` route (authenticated) → IntegrationsWizardPage mode="settings"
    - _Requirements: 8.1_

  - [x] 9.3 Write unit tests for IntegrationsWizardPage
    - Test step navigation (next/back)
    - Test skip flow advances to next step
    - Test summary page shows correct configured/skipped counts
    - Test settings mode shows all groups with current status
    - _Requirements: 2.1, 3.1, 3.6, 8.2_

- [x] 10. Checkpoint — Frontend verification
  - Ensure all frontend tests pass, ask the user if questions arise.

- [ ] 11. Implement setup.sh bootstrap script
  - [x] 11.1 Create `setup.sh` at repository root
    - Add shebang `#!/usr/bin/env bash` and POSIX-compatible syntax
    - Implement `detect_os()` — returns macos, ubuntu, fedora, arch, unknown
    - Implement `check_dependency(name, min_version, check_cmd)` — checks Docker, Docker Compose, Node.js 18+, Python 3.11+
    - Implement `suggest_install(name, os)` — prints platform-specific install commands (brew for macOS, apt/dnf/pacman for Linux)
    - Implement `check_ports()` — verify ports 5432, 6379, 8000, 3000 are free, identify conflicting process
    - Implement `wait_healthy(service, timeout)` — poll docker health status with 60s timeout
    - Implement main flow: detect OS → check deps → create venv → install backend deps → npm ci → docker compose up → wait healthy → start backend → start frontend → open browser
    - Print colored status messages for each phase
    - Handle errors gracefully with troubleshooting suggestions
    - Make executable (chmod +x)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_

  - [x] 11.2 Write property test for port conflict detection
    - **Property 8: Port conflict detection**
    - Generate random port occupation scenarios for ports in {5432, 6379, 8000, 3000}, mock socket binding, assert check_ports() detects all conflicts and returns port number + process info
    - **Validates: Requirements 9.5**

  - [x] 11.3 Run shellcheck lint on setup.sh
    - Ensure POSIX compliance and no Bash 4.0+ features
    - Fix any shellcheck warnings
    - _Requirements: 9.4_

- [ ] 12. Create production-grade README
  - [x] 12.1 Write comprehensive `README.md` at repository root
    - Table of Contents with all sections
    - Project Overview: what LOHI-TRADE is, key capabilities
    - Architecture: ASCII diagram showing Frontend ↔ Backend Gateway ↔ Trading Engine / Research Dashboard ↔ Redis/PostgreSQL ↔ External Services
    - Prerequisites: Docker, Docker Compose, Node.js 18+, Python 3.11+
    - Quick Start: `git clone` → `./setup.sh` → configure in browser → start trading
    - Manual Setup: step-by-step alternative to setup.sh
    - Configuration Reference: all environment variables with descriptions
    - External Services: table with service name, purpose, required/optional, signup URL for each (NVIDIA NIM, Nubra.io, Shoonya, Telegram, Ollama)
    - Development Workflow: how to run tests, lint, format
    - Testing: how to run unit tests, property tests, integration tests
    - Deployment: production considerations
    - Troubleshooting: Docker issues, port conflicts, DB failures, API key errors, macOS vs Linux differences
    - Contributing: guidelines for contributors
    - License section
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

- [ ] 13. Integration wiring and graceful degradation
  - [x] 13.1 Implement graceful degradation in existing app components
    - Add ServiceRegistry check at app startup (load registry, cache in memory)
    - Add feature gate utility function `is_feature_available(feature_name)` for use in route handlers
    - Add ServiceStatusBanner to Research Dashboard, Trading pages, and Notifications page when their dependencies are unconfigured
    - Ensure navigation items show "unconfigured" badge for disabled features
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [x] 13.2 Implement hot-reload for credential updates
    - When credentials are updated via `/settings/integrations`, trigger service reconnection
    - Update service status in registry within 5 seconds of successful reconnection
    - If reconnection fails, retain old credentials and show error
    - _Requirements: 8.3, 8.4, 8.5_

  - [x] 13.3 Write integration tests for full wizard flow
    - Test: enter credentials → test connection → complete setup → verify registry updated
    - Test: update credential → verify service reconnects
    - Test: skip all optional → verify degraded mode works correctly
    - _Requirements: 2.4, 3.2, 6.1, 8.3_

- [x] 14. Final checkpoint — Full integration verification
  - Ensure all tests pass (backend + frontend + property tests), ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document (Properties 1-8)
- Unit tests validate specific examples and edge cases
- Backend uses Python (FastAPI + Hypothesis for PBT), Frontend uses TypeScript (React + fast-check for PBT)
- The `setup.sh` script uses POSIX-compatible Bash (3.2+)
