"""Service Registry — tracks configuration state of external services.

Manages which external services (NVIDIA NIM, Nubra.io, Broker APIs,
Telegram, Ollama) are configured, unconfigured, or skipped. Exposes
feature availability based on service dependencies.

The registry persists state to ``data/service_registry.json`` — a simple
JSON file that requires no database migration. Loaded at startup, cached
in memory, and written on every state change.

Requirements: 3.4, 4.1, 4.6
Design: §Service Registry
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── Enums ───────────────────────────────────────────────────────────────────


class ServiceStatus(str, Enum):
    CONFIGURED = "configured"
    UNCONFIGURED = "unconfigured"
    SKIPPED = "skipped"
    ERROR = "error"


# ── Credential Group Definition ─────────────────────────────────────────────


@dataclass
class CredentialGroup:
    """Static definition of a credential group (external service)."""

    group_id: str
    name: str
    description: str
    required: bool
    env_file: str  # ".env" or ".env.research"
    credential_keys: list[str]
    validation_patterns: dict[str, str]  # key → regex pattern
    documentation_url: str
    tooltip_hints: dict[str, str]  # key → hint text
    features_dependent: list[str]


# ── Static Credential Group Definitions ─────────────────────────────────────


CREDENTIAL_GROUPS: list[CredentialGroup] = [
    CredentialGroup(
        group_id="nvidia_nim",
        name="NVIDIA NIM",
        description=(
            "Cloud AI inference for research analysis. Powers the Research "
            "Dashboard's multi-agent RAG pipeline with fast LLM responses. "
            "Free tier available — no credit card required."
        ),
        required=False,
        env_file=".env.research",
        credential_keys=["NVIDIA_NIM_API_KEY"],
        validation_patterns={"NVIDIA_NIM_API_KEY": r"^nvapi-[A-Za-z0-9_-]{20,}$"},
        documentation_url="https://build.nvidia.com",
        tooltip_hints={
            "NVIDIA_NIM_API_KEY": (
                "Sign in at build.nvidia.com → click avatar → API Keys → "
                "Generate Key. Starts with 'nvapi-'."
            )
        },
        features_dependent=["research_dashboard", "ai_analysis"],
    ),
    CredentialGroup(
        group_id="nubra",
        name="Nubra.io Market Data",
        description=(
            "Exchange-sourced NSE/BSE market data feed. Provides real-time "
            "stock quotes, intraday charts, and live tick streaming. "
            "Free trading account at nubra.io."
        ),
        required=False,
        env_file=".env",
        credential_keys=["NUBRA_PHONE_NO", "NUBRA_MPIN", "NUBRA_TOTP_SECRET"],
        validation_patterns={
            "NUBRA_PHONE_NO": r"^\d{10}$",
            "NUBRA_MPIN": r"^\d{4,6}$",
            "NUBRA_TOTP_SECRET": r"^[A-Za-z0-9+/=]{16,}$",
        },
        documentation_url="https://nubra.io",
        tooltip_hints={
            "NUBRA_PHONE_NO": "Your 10-digit registered mobile number on Nubra.io",
            "NUBRA_MPIN": "4-6 digit MPIN set during Nubra.io registration",
            "NUBRA_TOTP_SECRET": (
                "TOTP secret from Nubra.io 2FA setup. Run "
                "'python scripts/nubra_setup_totp.py' to generate."
            ),
        },
        features_dependent=["live_market_data", "real_time_quotes", "tick_streaming"],
    ),
    CredentialGroup(
        group_id="broker_shoonya",
        name="Shoonya (Finvasia) Broker",
        description=(
            "Primary broker for live order execution on NSE/BSE. "
            "Required only for real-money trading — paper trading works "
            "without any broker credentials."
        ),
        required=False,
        env_file=".env",
        credential_keys=["SHOONYA_API_KEY", "SHOONYA_CLIENT_ID", "SHOONYA_PASSWORD"],
        validation_patterns={
            "SHOONYA_API_KEY": r"^.{8,}$",
            "SHOONYA_CLIENT_ID": r"^[A-Z0-9]{4,}$",
            "SHOONYA_PASSWORD": r"^.{4,}$",
        },
        documentation_url="https://shoonya.finvasia.com/api-documentation",
        tooltip_hints={
            "SHOONYA_API_KEY": "API key from Shoonya developer portal",
            "SHOONYA_CLIENT_ID": "Your Shoonya trading account client ID (uppercase)",
            "SHOONYA_PASSWORD": "Your Shoonya account password",
        },
        features_dependent=["live_trading", "order_execution"],
    ),
    CredentialGroup(
        group_id="broker_angelone",
        name="Angel One Broker",
        description=(
            "Backup broker for order execution. Provides redundancy if "
            "the primary broker is unavailable. Optional — single broker "
            "is sufficient for most users."
        ),
        required=False,
        env_file=".env",
        credential_keys=["ANGELONE_API_KEY", "ANGELONE_CLIENT_ID", "ANGELONE_PASSWORD"],
        validation_patterns={
            "ANGELONE_API_KEY": r"^.{8,}$",
            "ANGELONE_CLIENT_ID": r"^[A-Z0-9]{4,}$",
            "ANGELONE_PASSWORD": r"^.{4,}$",
        },
        documentation_url="https://smartapi.angelone.in/docs",
        tooltip_hints={
            "ANGELONE_API_KEY": "API key from Angel One SmartAPI portal",
            "ANGELONE_CLIENT_ID": "Your Angel One client ID",
            "ANGELONE_PASSWORD": "Your Angel One account password",
        },
        features_dependent=["live_trading", "order_execution"],
    ),
    CredentialGroup(
        group_id="telegram",
        name="Telegram Bot",
        description=(
            "Trade notifications and alerts via Telegram. Sends real-time "
            "updates on order fills, strategy signals, and risk events. "
            "Optional — all alerts also appear in the web dashboard."
        ),
        required=False,
        env_file=".env",
        credential_keys=["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"],
        validation_patterns={
            "TELEGRAM_BOT_TOKEN": r"^\d+:[A-Za-z0-9_-]{35,}$",
            "TELEGRAM_CHAT_ID": r"^-?\d+$",
        },
        documentation_url="https://core.telegram.org/bots#how-do-i-create-a-bot",
        tooltip_hints={
            "TELEGRAM_BOT_TOKEN": (
                "Create a bot via @BotFather on Telegram. "
                "The token looks like '123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11'."
            ),
            "TELEGRAM_CHAT_ID": (
                "Your personal chat ID or group ID. "
                "Send a message to @userinfobot to find yours."
            ),
        },
        features_dependent=["telegram_notifications"],
    ),
    CredentialGroup(
        group_id="ollama",
        name="Ollama (Local AI)",
        description=(
            "Run AI models locally on your machine — fully private, no "
            "data leaves your computer. Alternative to NVIDIA NIM for "
            "research features. Requires ~5 GB disk for the model."
        ),
        required=False,
        env_file=".env.research",
        credential_keys=[],  # No credentials — just needs Ollama running
        validation_patterns={},
        documentation_url="https://ollama.com/download",
        tooltip_hints={},
        features_dependent=["research_dashboard_local", "ai_analysis_local"],
    ),
]

# Lookup by group_id for O(1) access
_GROUPS_BY_ID: dict[str, CredentialGroup] = {g.group_id: g for g in CREDENTIAL_GROUPS}


# ── Feature Dependency Map ──────────────────────────────────────────────────

# The `|` operator means "any one of these groups being configured satisfies
# the dependency." A feature is available if ALL its dependency expressions
# are satisfied.
FEATURE_DEPENDENCIES: dict[str, list[str]] = {
    "research_dashboard": ["nvidia_nim|ollama"],
    "ai_analysis": ["nvidia_nim|ollama"],
    "research_dashboard_local": ["ollama"],
    "ai_analysis_local": ["ollama"],
    "live_market_data": ["nubra"],
    "real_time_quotes": ["nubra"],
    "tick_streaming": ["nubra"],
    "live_trading": ["broker_shoonya|broker_angelone"],
    "order_execution": ["broker_shoonya|broker_angelone"],
    "telegram_notifications": ["telegram"],
}


# ── Service Registry Class ──────────────────────────────────────────────────


class ServiceRegistry:
    """Tracks configuration state and feature availability.

    Persists to a JSON file so state survives restarts without
    requiring a database migration.
    """

    def __init__(self, registry_path: str | Path = "data/service_registry.json"):
        self.registry_path = Path(registry_path)
        self._state: dict[str, dict[str, Any]] = {}
        self._setup_complete: bool = False
        self._completed_at: str | None = None
        self._load()

    # ── Public API ──────────────────────────────────────────────────────

    def get_status(self, group_id: str) -> ServiceStatus:
        """Get the current status of a credential group."""
        entry = self._state.get(group_id)
        if entry is None:
            return ServiceStatus.UNCONFIGURED
        return ServiceStatus(entry.get("status", "unconfigured"))

    def set_status(self, group_id: str, status: ServiceStatus) -> None:
        """Update the status of a credential group and persist."""
        if group_id not in self._state:
            self._state[group_id] = {}
        self._state[group_id]["status"] = status.value
        self._state[group_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save()

    def get_all_statuses(self) -> dict[str, ServiceStatus]:
        """Return status for every registered credential group."""
        result = {}
        for group in CREDENTIAL_GROUPS:
            result[group.group_id] = self.get_status(group.group_id)
        return result

    def get_available_features(self) -> dict[str, bool]:
        """Compute which features are available based on configured services."""
        statuses = self.get_all_statuses()
        result = {}
        for feature, deps in FEATURE_DEPENDENCIES.items():
            result[feature] = self._is_feature_satisfied(deps, statuses)
        return result

    def is_feature_available(self, feature: str) -> bool:
        """Check if a specific feature is available."""
        if feature not in FEATURE_DEPENDENCIES:
            return True  # Unknown features are assumed available
        statuses = self.get_all_statuses()
        return self._is_feature_satisfied(FEATURE_DEPENDENCIES[feature], statuses)

    @property
    def setup_complete(self) -> bool:
        return self._setup_complete

    def mark_setup_complete(self) -> None:
        """Mark the initial setup as complete."""
        self._setup_complete = True
        self._completed_at = datetime.now(timezone.utc).isoformat()
        self._save()

    def get_group(self, group_id: str) -> CredentialGroup | None:
        """Get the static definition for a credential group."""
        return _GROUPS_BY_ID.get(group_id)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the full registry state for API responses."""
        return {
            "setup_complete": self._setup_complete,
            "completed_at": self._completed_at,
            "services": {
                group.group_id: {
                    "group_id": group.group_id,
                    "name": group.name,
                    "description": group.description,
                    "required": group.required,
                    "status": self.get_status(group.group_id).value,
                    "features_affected": group.features_dependent,
                    "documentation_url": group.documentation_url,
                    "credential_keys": group.credential_keys,
                    "tooltip_hints": group.tooltip_hints,
                }
                for group in CREDENTIAL_GROUPS
            },
        }

    # ── Internal ────────────────────────────────────────────────────────

    def _is_feature_satisfied(self, deps: list[str], statuses: dict[str, ServiceStatus]) -> bool:
        """Check if all dependency expressions are satisfied.

        Each dep is a string like "nvidia_nim|ollama" meaning any one
        of the listed groups being CONFIGURED satisfies it.
        """
        for dep_expr in deps:
            alternatives = [g.strip() for g in dep_expr.split("|")]
            if not any(statuses.get(alt) == ServiceStatus.CONFIGURED for alt in alternatives):
                return False
        return True

    def _load(self) -> None:
        """Load state from JSON file, creating defaults if missing."""
        if not self.registry_path.exists():
            self._init_defaults()
            return
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
            self._setup_complete = data.get("setup_complete", False)
            self._completed_at = data.get("completed_at")
            self._state = data.get("services", {})
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "Service registry file corrupted or unreadable (%s); resetting to defaults",
                exc,
            )
            self._init_defaults()

    def _init_defaults(self) -> None:
        """Initialize with all services unconfigured."""
        self._setup_complete = False
        self._completed_at = None
        self._state = {
            group.group_id: {"status": "unconfigured", "updated_at": None}
            for group in CREDENTIAL_GROUPS
        }
        self._save()

    def _save(self) -> None:
        """Persist current state to JSON file."""
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "setup_complete": self._setup_complete,
            "completed_at": self._completed_at,
            "services": self._state,
        }
        try:
            self.registry_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            logger.error("Failed to save service registry: %s", exc)
