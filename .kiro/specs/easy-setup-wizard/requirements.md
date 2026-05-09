# Requirements Document

## Introduction

The Easy Setup Wizard provides a streamlined onboarding experience for LOHI-TRADE. New developers should be able to clone the repository and reach a running application with minimal friction — ideally a single command. The wizard presents a browser-based UI where users can enter API keys, understand what each service does, skip optional configuration, and get the system running in a degraded-but-functional mode without any paid credentials. A production-grade README accompanies the wizard to explain architecture, data flows, and operational details.

## Glossary

- **Setup_Wizard**: The browser-based UI page that guides users through initial configuration of API keys and service credentials
- **Setup_CLI**: The command-line bootstrap script that installs dependencies, starts infrastructure, and launches the Setup_Wizard
- **Configuration_Store**: The backend service that persists user-provided credentials to `.env` and `.env.research` files
- **Service_Registry**: The internal registry that tracks which external services are configured, unconfigured, or skipped
- **Credential_Group**: A logical grouping of related API keys/secrets belonging to a single external service (e.g., all Nubra.io fields form one Credential_Group)
- **Graceful_Degradation**: The system's ability to start and operate with reduced functionality when optional Credential_Groups are not configured
- **Health_Dashboard**: A UI panel showing the connection status of all configured services after setup completes
- **README_Generator**: Not applicable — the README is a static production-grade markdown file committed to the repository

## Requirements

### Requirement 1: One-Command Bootstrap

**User Story:** As a new developer, I want to clone the repo and run a single command to get the entire system running, so that I can start exploring LOHI-TRADE without manual multi-step setup.

#### Acceptance Criteria

1. WHEN a user executes `./setup.sh` from the repository root, THE Setup_CLI SHALL check for required system dependencies (Docker, Docker Compose, Node.js 18+, Python 3.11+) and report any missing dependencies with installation instructions
2. WHEN all system dependencies are satisfied, THE Setup_CLI SHALL create Python virtual environment, install backend dependencies, install frontend dependencies, start Docker infrastructure (PostgreSQL, Redis), and launch the backend gateway and frontend application
3. WHEN the bootstrap process completes successfully, THE Setup_CLI SHALL open the user's default browser to the Setup_Wizard page at `http://localhost:3000/setup`
4. IF a system dependency is missing, THEN THE Setup_CLI SHALL display the dependency name, required minimum version, and a platform-specific installation command (macOS/Linux)
5. IF Docker containers fail to start within 60 seconds, THEN THE Setup_CLI SHALL display the container logs and a troubleshooting suggestion
6. THE Setup_CLI SHALL complete the full bootstrap process (excluding dependency installation) within 120 seconds on a standard broadband connection

### Requirement 2: Setup Wizard UI — Credential Entry

**User Story:** As a new developer, I want a guided UI to enter my API keys with clear explanations of what each service does, so that I understand the system's external dependencies before committing credentials.

#### Acceptance Criteria

1. THE Setup_Wizard SHALL display Credential_Groups in a step-by-step flow with the following order: NVIDIA NIM (required for AI research), Nubra.io (required for live market data), Broker APIs (optional), Telegram Bot (optional), Ollama (optional local AI)
2. WHEN a Credential_Group is displayed, THE Setup_Wizard SHALL show: the service name, a plain-language explanation of why the service is needed (2-3 sentences), a link to the service's signup/documentation page, and labeled input fields for each required credential
3. WHEN the user enters a credential value, THE Setup_Wizard SHALL mask the input field by default and provide a toggle to reveal the value
4. WHEN the user submits a Credential_Group, THE Configuration_Store SHALL validate the format of each credential (non-empty, expected character pattern) and display inline validation errors for malformed entries
5. THE Setup_Wizard SHALL indicate which Credential_Groups are required for core functionality and which are optional enhancements
6. WHEN the user hovers over or focuses on a credential input field, THE Setup_Wizard SHALL display a tooltip explaining where to find that specific value (e.g., "Find this in your NVIDIA NIM dashboard under API Keys")

### Requirement 3: Skip-and-Configure-Later Flow

**User Story:** As a new developer, I want to skip optional API key configuration and still get a working system, so that I can explore the platform before committing to external service signups.

#### Acceptance Criteria

1. WHEN a Credential_Group is marked as optional, THE Setup_Wizard SHALL display a "Skip for now" button that advances to the next step without requiring any input
2. WHEN the user skips all optional Credential_Groups, THE Setup_Wizard SHALL complete setup and launch the application in a degraded mode where only configured services are active
3. WHEN the user skips the NVIDIA NIM Credential_Group, THE Setup_Wizard SHALL offer the Ollama local alternative and explain that AI research features will be unavailable until either NVIDIA NIM or Ollama is configured
4. THE Service_Registry SHALL persist the skip/configured status of each Credential_Group so that the Setup_Wizard can resume from where the user left off on subsequent visits
5. WHEN the user navigates to the Setup_Wizard after initial setup, THE Setup_Wizard SHALL display previously skipped Credential_Groups as "Not configured" with a "Configure now" action
6. THE Setup_Wizard SHALL display a summary page before finalizing that shows all configured services, all skipped services, and the features that will be unavailable due to skipped services

### Requirement 4: Graceful Degradation

**User Story:** As a developer running LOHI-TRADE with partial configuration, I want the system to clearly indicate which features are available and which are disabled, so that I understand the current operational state.

#### Acceptance Criteria

1. WHEN the application starts with unconfigured optional services, THE Service_Registry SHALL disable only the features that depend on those services and leave all other features fully operational
2. WHEN a user navigates to a feature that requires an unconfigured service, THE Setup_Wizard SHALL display an inline banner explaining which service is needed and a direct link to configure it
3. WHILE the NVIDIA NIM Credential_Group is unconfigured and Ollama is not running, THE Service_Registry SHALL disable the Research Dashboard and display a message indicating the required configuration
4. WHILE no Broker API Credential_Group is configured, THE Service_Registry SHALL restrict the Trading subsystem to paper-trading mode only
5. WHILE the Telegram Bot Credential_Group is unconfigured, THE Service_Registry SHALL disable trade notifications and log a warning at startup
6. THE Service_Registry SHALL expose a `/api/health/services` endpoint that returns the configuration status and availability of each external service

### Requirement 5: Credential Persistence and Security

**User Story:** As a developer, I want my API keys stored securely on my local machine and never committed to version control, so that my credentials remain safe.

#### Acceptance Criteria

1. WHEN the user submits credentials through the Setup_Wizard, THE Configuration_Store SHALL write trading-related credentials to `.env` and research-related credentials to `.env.research` in the repository root
2. THE Configuration_Store SHALL verify that `.env` and `.env.research` are listed in `.gitignore` before writing any credentials
3. IF `.env` or `.env.research` are not in `.gitignore`, THEN THE Configuration_Store SHALL add them to `.gitignore` before writing credentials and display a warning to the user
4. THE Configuration_Store SHALL set file permissions on `.env` and `.env.research` to owner-read-write only (chmod 600) on Unix systems
5. WHEN credentials are transmitted from the Setup_Wizard to the backend, THE Configuration_Store SHALL accept them only over localhost connections (reject non-loopback origins)
6. THE Configuration_Store SHALL never log credential values — only log credential key names and success/failure status

### Requirement 6: Service Connection Validation

**User Story:** As a developer, I want to verify that my entered API keys actually work before completing setup, so that I can fix issues immediately rather than discovering them later.

#### Acceptance Criteria

1. WHEN the user submits a Credential_Group, THE Setup_Wizard SHALL offer a "Test Connection" button that validates the credentials against the external service
2. WHEN the "Test Connection" succeeds, THE Setup_Wizard SHALL display a green checkmark and the service response time
3. IF the "Test Connection" fails, THEN THE Setup_Wizard SHALL display the error message, a suggested fix (e.g., "Check that your API key has not expired"), and allow the user to retry
4. WHEN testing NVIDIA NIM credentials, THE Configuration_Store SHALL make a lightweight model-list API call to verify the key is valid
5. WHEN testing Nubra.io credentials, THE Configuration_Store SHALL attempt a login handshake and report success or the specific authentication failure reason
6. THE Setup_Wizard SHALL allow the user to proceed without testing (with a warning) if the external service is temporarily unreachable

### Requirement 7: Production-Grade README

**User Story:** As a new contributor, I want a comprehensive README that explains the system architecture, setup process, and how all components connect, so that I can understand the project without reading every source file.

#### Acceptance Criteria

1. THE README SHALL contain the following sections: Project Overview, Architecture Diagram (ASCII), Prerequisites, Quick Start (single command), Manual Setup, Configuration Reference, External Services Explained, Development Workflow, Testing, Deployment, Troubleshooting, and Contributing
2. THE README SHALL include an ASCII architecture diagram showing the relationship between Frontend, Backend Gateway, Trading Engine, Research Dashboard, Redis, PostgreSQL, and all external services
3. THE README SHALL explain each external service (NVIDIA NIM, Nubra.io, Broker APIs, Telegram, Ollama) with: what it does, why LOHI-TRADE needs it, whether it is required or optional, and how to obtain credentials
4. THE README SHALL document the Quick Start flow as: clone → run `./setup.sh` → configure in browser → start trading/researching
5. THE README SHALL include a troubleshooting section covering: Docker not running, port conflicts, database connection failures, API key validation failures, and common platform-specific issues (macOS vs Linux)
6. THE README SHALL be formatted with a table of contents, consistent heading hierarchy, and code blocks for all commands

### Requirement 8: Setup Wizard — Settings Page Integration

**User Story:** As a returning user, I want to access the setup wizard from within the running application to add or update API keys later, so that I do not need to re-run the bootstrap script.

#### Acceptance Criteria

1. THE Setup_Wizard SHALL be accessible from the application's Settings page at the route `/settings/integrations`
2. WHEN the user navigates to `/settings/integrations`, THE Setup_Wizard SHALL display all Credential_Groups with their current status (configured, not configured, connection error)
3. WHEN the user updates a credential, THE Configuration_Store SHALL write the new value to the appropriate `.env` file and trigger a service reconnection without requiring an application restart
4. WHEN a service reconnection succeeds after credential update, THE Health_Dashboard SHALL update the service status to "Connected" within 5 seconds
5. IF a service reconnection fails after credential update, THEN THE Health_Dashboard SHALL display the previous status and the error reason, and retain the old credential value until the user confirms the change
6. THE Setup_Wizard SHALL provide a "Reset to defaults" action per Credential_Group that clears the stored credentials and returns the service to unconfigured state

### Requirement 9: Cross-Platform Compatibility

**User Story:** As a developer on macOS or Linux, I want the setup process to work on my operating system without platform-specific workarounds, so that I can contribute regardless of my development environment.

#### Acceptance Criteria

1. THE Setup_CLI SHALL detect the operating system (macOS, Ubuntu/Debian, Fedora/RHEL, Arch Linux) and provide platform-appropriate dependency installation commands
2. WHEN running on macOS, THE Setup_CLI SHALL check for Homebrew and suggest `brew install` commands for missing dependencies
3. WHEN running on Linux, THE Setup_CLI SHALL detect the package manager (apt, dnf, pacman) and suggest appropriate install commands
4. THE Setup_CLI SHALL use POSIX-compatible shell syntax (#!/usr/bin/env bash) and avoid Bash-specific features above version 4.0 that are unavailable on macOS default shell
5. IF the user's system has port conflicts (5432, 6379, 8000, 3000 already in use), THEN THE Setup_CLI SHALL detect the conflict, identify the conflicting process, and suggest either killing it or using alternative ports
6. THE Setup_CLI SHALL function correctly with both Docker Desktop (macOS) and native Docker Engine (Linux)
