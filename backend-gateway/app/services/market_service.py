"""Market Service — orchestrates market selection, tax generation, and profile management.

Provides the backend logic for the setup wizard's country selection step
and the settings page for market/tax configuration.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

# Add src to path for market imports
_src_path = str(Path(__file__).resolve().parents[3])
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)

from src.markets.market_profile import Country, TaxProfile
from src.markets.market_registry import MarketRegistry, get_market_registry
from src.markets.tax_engine import TaxEngine
from src.markets.tax_profile_generator import (
    TaxGenerationError,
    TaxProfileGenerator,
)

logger = logging.getLogger(__name__)


class MarketService:
    """Orchestrates market selection and tax profile management.

    Used by the setup wizard (Step 1: Country Selection) and the
    settings page for ongoing market/tax configuration.
    """

    def __init__(self, registry: Optional[MarketRegistry] = None):
        self._registry = registry or get_market_registry()
        self._tax_generator = TaxProfileGenerator()  # No LLM by default
        self._tax_engine: Optional[TaxEngine] = None

        # Initialize tax engine if market is already configured
        if self._registry.active_profile:
            self._tax_engine = TaxEngine(self._registry.active_profile)

    # ── Setup Wizard API ────────────────────────────────────────────────

    def get_available_countries(self) -> list[dict]:
        """Return list of available countries for the setup wizard dropdown."""
        return self._registry.get_available_countries()

    def get_market_status(self) -> dict:
        """Return current market configuration status."""
        profile = self._registry.active_profile
        if profile is None:
            return {
                "configured": False,
                "country": None,
                "message": "No market selected. Please complete setup.",
            }

        return {
            "configured": True,
            "country": profile.country.value,
            "country_name": profile.country_name,
            "currency": profile.currency,
            "currency_symbol": profile.currency_symbol,
            "timezone": profile.timezone,
            "primary_exchange": profile.primary_exchange.value,
            "benchmark_index": profile.benchmark_index_name,
            "regulator": profile.regulator,
            "tax_verified": profile.tax_profile.verified_by_user,
            "broker_count": len(profile.available_brokers),
        }

    def select_country(self, country_code: str) -> dict:
        """Select a country during setup wizard.

        Args:
            country_code: ISO 2-letter code (e.g., "IN", "US", "UK")

        Returns:
            Full market profile summary for frontend display

        Raises:
            ValueError: If country is not supported
        """
        profile = self._registry.select_market(country_code)
        self._tax_engine = TaxEngine(profile)

        return {
            "country": profile.country.value,
            "country_name": profile.country_name,
            "currency": profile.currency,
            "currency_symbol": profile.currency_symbol,
            "timezone": profile.timezone,
            "primary_exchange": profile.primary_exchange.value,
            "exchanges": [e.value for e in profile.exchanges],
            "benchmark_index": profile.benchmark_index_name,
            "sessions": {
                "market_open": profile.sessions.market_open.strftime("%H:%M"),
                "trading_start": profile.sessions.trading_start.strftime("%H:%M"),
                "trading_end": profile.sessions.trading_end.strftime("%H:%M"),
                "square_off_time": profile.sessions.square_off_time.strftime("%H:%M"),
                "market_close": profile.sessions.market_close.strftime("%H:%M"),
            },
            "settlement_cycle": profile.settlement_cycle.value,
            "available_brokers": [
                {
                    "broker_id": b.broker_id,
                    "name": b.name,
                    "description": b.description,
                    "supports_paper_trading": b.supports_paper_trading,
                    "commission_model": b.commission_model,
                }
                for b in profile.available_brokers
            ],
            "tax_profile": {
                "source": profile.tax_profile.source,
                "verified": profile.tax_profile.verified_by_user,
                "short_term_cgt_pct": profile.tax_profile.capital_gains_short_term_pct,
                "long_term_cgt_pct": profile.tax_profile.capital_gains_long_term_pct,
                "threshold_days": profile.tax_profile.short_term_threshold_days,
                "wash_sale_rule": profile.tax_profile.wash_sale_rule,
                "transaction_taxes_count": len(profile.tax_profile.transaction_taxes),
                "disclaimer": profile.tax_profile.disclaimer,
            },
            "default_symbols": profile.default_symbols[:10],
            "regulator": profile.regulator,
            "supports_short_selling": profile.supports_short_selling,
            "supports_options": profile.supports_options,
            "supports_futures": profile.supports_futures,
        }

    def get_profile_detail(self, country_code: str) -> Optional[dict]:
        """Get full profile details for a specific country (for preview)."""
        profile = self._registry.get_profile(country_code)
        if profile is None:
            return None

        return profile.model_dump(mode="json")

    # ── Tax Profile API ─────────────────────────────────────────────────

    def get_tax_profile(self) -> Optional[dict]:
        """Get the active market's tax profile."""
        profile = self._registry.active_profile
        if profile is None:
            return None
        return profile.tax_profile.model_dump(mode="json")

    async def generate_tax_profile(self, country_code: str) -> dict:
        """Generate a tax profile using AI for the given country.

        Returns the generated profile for user review (not yet applied).
        """
        profile = self._registry.get_profile(country_code)
        if profile is None:
            raise ValueError(f"Unknown country: {country_code}")

        try:
            generated = await self._tax_generator.generate(
                Country(country_code), profile.country_name
            )
            return {
                "success": True,
                "profile": generated.model_dump(mode="json"),
                "requires_verification": True,
                "message": "Tax profile generated. Please review and confirm.",
            }
        except TaxGenerationError as e:
            return {
                "success": False,
                "error": str(e),
                "message": "Using pre-built tax profile instead.",
                "fallback_profile": profile.tax_profile.model_dump(mode="json"),
            }

    async def refresh_tax_profile(self) -> dict:
        """Refresh the active market's tax profile using AI."""
        profile = self._registry.active_profile
        if profile is None:
            raise ValueError("No market configured")

        try:
            diff = await self._tax_generator.refresh(profile.tax_profile, profile.country_name)
            return {
                "success": True,
                "diff": diff.to_dict(),
                "message": "Review the changes below and confirm to apply.",
            }
        except TaxGenerationError as e:
            return {
                "success": False,
                "error": str(e),
                "message": "Could not refresh tax profile. Current profile unchanged.",
            }

    def confirm_tax_profile(self, tax_data: dict) -> dict:
        """Confirm and apply a tax profile after user review.

        Args:
            tax_data: Validated tax profile data from the frontend

        Returns:
            Confirmation response
        """
        profile = self._registry.active_profile
        if profile is None:
            raise ValueError("No market configured")

        # Mark as verified
        tax_data["verified_by_user"] = True

        try:
            tax_profile = TaxProfile.model_validate(tax_data)
        except Exception as e:
            raise ValueError(f"Invalid tax profile data: {e}")

        # Apply to registry
        self._registry.update_tax_profile(profile.country.value, tax_profile)

        # Refresh tax engine
        updated_profile = self._registry.active_profile
        if updated_profile:
            self._tax_engine = TaxEngine(updated_profile)

        return {
            "success": True,
            "message": "Tax profile confirmed and saved.",
            "verified": True,
        }

    # ── Charge Estimation API ───────────────────────────────────────────

    def estimate_charges(
        self,
        trade_value: float,
        side: str,
        is_intraday: bool = False,
        brokerage: float = 0.0,
    ) -> Optional[dict]:
        """Estimate transaction charges for a trade.

        Used by the order ticket to show estimated charges before submission.
        """
        if self._tax_engine is None:
            return None

        estimate = self._tax_engine.estimate_transaction_charges(
            trade_value=trade_value,
            side=side,
            is_intraday=is_intraday,
            brokerage_amount=brokerage,
        )

        return {
            "trade_value": estimate.trade_value,
            "currency": estimate.currency,
            "charges": [
                {
                    "name": c.name,
                    "amount": c.amount,
                    "rate_pct": c.rate_pct,
                    "description": c.description,
                }
                for c in estimate.charges
            ],
            "total_charges": estimate.total_charges,
            "effective_rate_pct": estimate.effective_rate_pct,
            "net_value": estimate.net_value,
            "disclaimer": estimate.disclaimer,
        }

    # ── Broker Info API ─────────────────────────────────────────────────

    def get_available_brokers(self) -> list[dict]:
        """Get brokers available for the active market."""
        profile = self._registry.active_profile
        if profile is None:
            return []

        return [
            {
                "broker_id": b.broker_id,
                "name": b.name,
                "description": b.description,
                "api_type": b.api_type,
                "documentation_url": b.documentation_url,
                "supports_paper_trading": b.supports_paper_trading,
                "supports_options": b.supports_options,
                "supports_futures": b.supports_futures,
                "commission_model": b.commission_model,
                "credential_keys": b.credential_keys,
            }
            for b in profile.available_brokers
        ]
