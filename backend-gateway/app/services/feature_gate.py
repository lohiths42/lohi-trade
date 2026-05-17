"""Feature Gate — utility for checking feature availability at runtime.

Provides a singleton ServiceRegistry instance loaded at module level
and a simple ``is_feature_available(feature_name)`` function that can
be used in route handlers or as a FastAPI dependency.

The registry is loaded once at import time and cached in memory.
It reads from ``data/service_registry.json`` relative to the repo root.

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5
Design: §Graceful Degradation
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import HTTPException

from app.services.service_registry import ServiceRegistry

logger = logging.getLogger(__name__)

# ── Singleton Registry ──────────────────────────────────────────────────────

_registry: Optional[ServiceRegistry] = None


def _get_repo_root() -> Path:
    """Resolve the repository root (two levels up from backend-gateway/app/)."""
    return Path(__file__).resolve().parents[3]


def get_registry() -> ServiceRegistry:
    """Return the cached ServiceRegistry singleton.

    Lazily initializes on first call. Thread-safe for read operations
    since Python's GIL protects the reference assignment.
    """
    global _registry
    if _registry is None:
        repo_root = _get_repo_root()
        registry_path = repo_root / "data" / "service_registry.json"
        _registry = ServiceRegistry(registry_path)
        logger.info("Feature gate: ServiceRegistry loaded from %s", registry_path)
    return _registry


def initialize_registry() -> ServiceRegistry:
    """Explicitly initialize the registry (called at app startup).

    Returns the registry instance for use in the lifespan context.
    """
    registry = get_registry()
    features = registry.get_available_features()
    available = [f for f, v in features.items() if v]
    unavailable = [f for f, v in features.items() if not v]
    logger.info(
        "Feature gate initialized — available: %s, unavailable: %s",
        available or "(none)",
        unavailable or "(none)",
    )
    return registry


def is_feature_available(feature_name: str) -> bool:
    """Check if a feature is available based on configured services.

    Args:
        feature_name: The feature identifier (e.g., "research_dashboard",
                      "live_trading", "telegram_notifications").

    Returns:
        True if the feature's service dependencies are satisfied.
    """
    registry = get_registry()
    return registry.is_feature_available(feature_name)


def get_available_features() -> dict[str, bool]:
    """Return the full feature availability map."""
    registry = get_registry()
    return registry.get_available_features()


# ── FastAPI Dependency ──────────────────────────────────────────────────────


def require_feature(feature_name: str):
    """Create a FastAPI dependency that gates a route on feature availability.

    Usage:
        @router.get("/research/...", dependencies=[Depends(require_feature("research_dashboard"))])
        async def research_endpoint(): ...

    Raises 503 Service Unavailable if the feature is not configured.
    """

    def _check() -> bool:
        if not is_feature_available(feature_name):
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "feature_unavailable",
                    "feature": feature_name,
                    "message": (
                        f"The '{feature_name}' feature is not available. "
                        "Please configure the required services at /settings/integrations."
                    ),
                },
            )
        return True

    return _check


def reload_registry() -> None:
    """Force-reload the registry from disk.

    Useful after credential updates to pick up new service statuses
    without restarting the application.
    """
    global _registry
    _registry = None
    get_registry()
    logger.info("Feature gate: registry reloaded")
