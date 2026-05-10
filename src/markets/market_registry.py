"""Market Registry — loads, caches, and manages market profiles.

Provides the single access point for the active market profile used
throughout the trading engine, RMS, and backend gateway. The active
market is selected during setup and persisted to config/market.yaml.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import ValidationError

from .market_profile import Country, MarketProfile
from .profiles import ALL_PROFILES

logger = logging.getLogger(__name__)

# Default market config path
MARKET_CONFIG_PATH = Path("config/market.yaml")


class MarketRegistry:
    """Registry of available market profiles and the active selection.

    Loads pre-built profiles for all supported countries and manages
    the user's active market selection (persisted to config/market.yaml).
    """

    def __init__(self, config_path: Path | None = None):
        self._config_path = config_path or MARKET_CONFIG_PATH
        self._profiles: dict[str, MarketProfile] = dict(ALL_PROFILES)
        self._active_profile: MarketProfile | None = None
        self._load_active()

    # ── Public API ──────────────────────────────────────────────────────

    @property
    def active_profile(self) -> MarketProfile | None:
        """The currently active market profile, or None if not yet selected."""
        return self._active_profile

    @property
    def active_country(self) -> Country | None:
        """The currently active country code."""
        if self._active_profile:
            return self._active_profile.country
        return None

    @property
    def is_configured(self) -> bool:
        """Whether a market has been selected and saved."""
        return self._active_profile is not None

    def get_available_countries(self) -> list[dict]:
        """Return list of available countries for the setup wizard.

        Returns a simplified list suitable for frontend dropdown rendering.
        """
        countries = []
        for code, profile in sorted(self._profiles.items(), key=lambda x: x[1].country_name):
            countries.append({
                "code": code,
                "name": profile.country_name,
                "currency": profile.currency,
                "currency_symbol": profile.currency_symbol,
                "primary_exchange": profile.primary_exchange.value,
                "timezone": profile.timezone,
                "regulator": profile.regulator,
                "broker_count": len(profile.available_brokers),
            })
        return countries

    def get_profile(self, country_code: str) -> MarketProfile | None:
        """Get the market profile for a specific country code."""
        return self._profiles.get(country_code)

    def select_market(self, country_code: str) -> MarketProfile:
        """Select and persist a market profile.

        Called during setup wizard Step 1 when user picks their country.
        Persists the selection to config/market.yaml.

        Args:
            country_code: ISO 2-letter country code (e.g., "IN", "US")

        Returns:
            The selected MarketProfile

        Raises:
            ValueError: If country_code is not supported

        """
        profile = self._profiles.get(country_code)
        if profile is None:
            supported = ", ".join(sorted(self._profiles.keys()))
            raise ValueError(
                f"Unsupported country code: '{country_code}'. "
                f"Supported: {supported}",
            )

        self._active_profile = profile
        self._save_active(profile)
        logger.info(
            "Market selected: %s (%s) — %s",
            profile.country_name,
            profile.primary_exchange.value,
            profile.timezone,
        )
        return profile

    def update_tax_profile(self, country_code: str, tax_profile) -> MarketProfile:
        """Update the tax profile for a market (after AI generation + user verification).

        Args:
            country_code: Country to update
            tax_profile: New TaxProfile (validated Pydantic model)

        Returns:
            Updated MarketProfile

        """
        profile = self._profiles.get(country_code)
        if profile is None:
            raise ValueError(f"Unknown country: {country_code}")

        # Create updated profile with new tax data
        updated = profile.model_copy(update={"tax_profile": tax_profile})
        self._profiles[country_code] = updated

        # If this is the active profile, update and persist
        if self._active_profile and self._active_profile.country.value == country_code:
            self._active_profile = updated
            self._save_active(updated)

        logger.info("Tax profile updated for %s", country_code)
        return updated

    def register_profile(self, profile: MarketProfile) -> None:
        """Register a custom market profile (for user-defined markets)."""
        self._profiles[profile.country.value] = profile
        logger.info("Custom profile registered: %s", profile.country_name)

    # ── Internal ────────────────────────────────────────────────────────

    def _load_active(self) -> None:
        """Load the active market selection from config/market.yaml."""
        if not self._config_path.exists():
            self._active_profile = None
            return

        try:
            with open(self._config_path) as f:
                data = yaml.safe_load(f)

            if not data or "country" not in data:
                self._active_profile = None
                return

            country_code = data["country"]
            profile = self._profiles.get(country_code)

            if profile is None:
                logger.warning(
                    "Saved market '%s' not found in registry; ignoring",
                    country_code,
                )
                self._active_profile = None
                return

            # If there's a custom tax_profile override in the saved config, apply it
            if "tax_profile_override" in data:
                from .market_profile import TaxProfile
                try:
                    custom_tax = TaxProfile.model_validate(data["tax_profile_override"])
                    profile = profile.model_copy(update={"tax_profile": custom_tax})
                except ValidationError as e:
                    logger.warning("Invalid saved tax profile override: %s", e)

            self._active_profile = profile
            logger.info(
                "Loaded active market: %s (%s)",
                profile.country_name,
                profile.primary_exchange.value,
            )

        except (yaml.YAMLError, OSError) as e:
            logger.error("Failed to load market config: %s", e)
            self._active_profile = None

    def _save_active(self, profile: MarketProfile) -> None:
        """Persist the active market selection to config/market.yaml."""
        self._config_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "# Market configuration — selected during setup wizard": None,
            "country": profile.country.value,
            "country_name": profile.country_name,
            "currency": profile.currency,
            "timezone": profile.timezone,
            "primary_exchange": profile.primary_exchange.value,
            "benchmark_index": profile.benchmark_index_name,
            "benchmark_symbol": profile.benchmark_symbol,
            "selected_at": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc,
            ).isoformat(),
        }

        # Include tax profile override if it differs from the built-in default
        builtin = ALL_PROFILES.get(profile.country.value)
        if builtin and profile.tax_profile != builtin.tax_profile:
            data["tax_profile_override"] = profile.tax_profile.model_dump()

        try:
            # Remove the comment key before writing
            clean_data = {k: v for k, v in data.items() if not k.startswith("#")}
            with open(self._config_path, "w") as f:
                f.write("# Market configuration — selected during setup wizard\n")
                f.write("# Do not edit manually; use the setup wizard or API\n\n")
                yaml.dump(clean_data, f, default_flow_style=False, sort_keys=False)

            logger.info("Market config saved to %s", self._config_path)
        except OSError as e:
            logger.error("Failed to save market config: %s", e)


# ── Global Instance ─────────────────────────────────────────────────────────

_registry: MarketRegistry | None = None


def get_market_registry(config_path: Path | None = None) -> MarketRegistry:
    """Get or create the global MarketRegistry instance."""
    global _registry
    if _registry is None:
        _registry = MarketRegistry(config_path)
    return _registry


def reload_market_registry(config_path: Path | None = None) -> MarketRegistry:
    """Force reload the market registry from disk."""
    global _registry
    _registry = MarketRegistry(config_path)
    return _registry
