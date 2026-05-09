"""Market Router — API endpoints for market selection and tax configuration.

Provides the backend for:
- Setup Wizard Step 1: Country selection
- Settings: Tax profile management and AI refresh
- Order Ticket: Charge estimation

All market selection endpoints are localhost-only (same as setup).
Charge estimation is available to authenticated users.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.services.market_service import MarketService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["market"])


# ── Pydantic Request/Response Models ───────────────────────────────────────


class CountrySelection(BaseModel):
    """Request body for country selection."""

    country_code: str = Field(
        description="ISO 2-letter country code (e.g., 'IN', 'US', 'UK')",
        min_length=2,
        max_length=2,
    )


class ChargeEstimateRequest(BaseModel):
    """Request body for charge estimation."""

    trade_value: float = Field(gt=0, description="Total trade value in local currency")
    side: str = Field(description="Trade side: 'buy' or 'sell'")
    is_intraday: bool = Field(default=False, description="Whether this is an intraday trade")
    brokerage: float = Field(default=0.0, ge=0, description="Broker commission amount")


class TaxProfileConfirmation(BaseModel):
    """Request body for confirming a tax profile."""

    tax_profile: dict = Field(description="The tax profile data to confirm")


class CountryInfo(BaseModel):
    """Response model for a single country option."""

    code: str
    name: str
    currency: str
    currency_symbol: str
    primary_exchange: str
    timezone: str
    regulator: str
    broker_count: int


class MarketStatusResponse(BaseModel):
    """Response model for market configuration status."""

    configured: bool
    country: Optional[str] = None
    country_name: Optional[str] = None
    currency: Optional[str] = None
    currency_symbol: Optional[str] = None
    timezone: Optional[str] = None
    primary_exchange: Optional[str] = None
    benchmark_index: Optional[str] = None
    regulator: Optional[str] = None
    tax_verified: Optional[bool] = None
    broker_count: Optional[int] = None
    message: Optional[str] = None


# ── Dependencies ────────────────────────────────────────────────────────────


def require_localhost(request: Request) -> bool:
    """Reject requests not from loopback address (for setup endpoints)."""
    client_host = request.client.host if request.client else None
    if client_host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(
            status_code=403,
            detail="Market setup endpoints are only accessible from localhost",
        )
    return True


def get_market_service() -> MarketService:
    """Dependency injection for MarketService."""
    return MarketService()


# ── Setup Endpoints (localhost-only) ────────────────────────────────────────


@router.get("/market/countries", response_model=list[CountryInfo])
async def list_available_countries(
    _localhost: bool = Depends(require_localhost),
    service: MarketService = Depends(get_market_service),
) -> list[CountryInfo]:
    """List all available countries for market selection.

    Returns countries with their basic info for the setup wizard dropdown.
    This is Step 1 of the setup wizard — user picks their country first.
    """
    countries = service.get_available_countries()
    return [CountryInfo(**c) for c in countries]


@router.get("/market/status", response_model=MarketStatusResponse)
async def get_market_status(
    service: MarketService = Depends(get_market_service),
) -> MarketStatusResponse:
    """Get current market configuration status.

    Available without localhost restriction — used by frontend to
    determine if market selection has been completed.
    """
    status = service.get_market_status()
    return MarketStatusResponse(**status)


@router.post("/market/select")
async def select_country(
    body: CountrySelection,
    _localhost: bool = Depends(require_localhost),
    service: MarketService = Depends(get_market_service),
) -> dict:
    """Select a country/market during setup.

    This is the primary action of Setup Wizard Step 1. Selecting a country:
    - Sets the timezone, currency, and trading hours
    - Configures the benchmark index for volatility guard
    - Determines available brokers (shown in Step 2)
    - Loads the tax profile (pre-built or AI-generated)
    - Sets default symbols for the watchlist

    The selection is persisted to config/market.yaml.
    """
    try:
        result = service.select_country(body.country_code.upper())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {"status": "ok", **result}


@router.get("/market/profile/{country_code}")
async def get_country_profile(
    country_code: str,
    _localhost: bool = Depends(require_localhost),
    service: MarketService = Depends(get_market_service),
) -> dict:
    """Get full profile details for a specific country (preview before selection)."""
    detail = service.get_profile_detail(country_code.upper())
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Country not found: {country_code}")
    return detail


@router.get("/market/brokers")
async def get_available_brokers(
    service: MarketService = Depends(get_market_service),
) -> dict:
    """Get brokers available for the currently selected market.

    Used by Setup Wizard Step 2 to show only relevant broker options.
    """
    brokers = service.get_available_brokers()
    if not brokers:
        raise HTTPException(
            status_code=400,
            detail="No market selected. Complete Step 1 first.",
        )
    return {"brokers": brokers}


# ── Tax Profile Endpoints ───────────────────────────────────────────────────


@router.get("/market/tax")
async def get_tax_profile(
    service: MarketService = Depends(get_market_service),
) -> dict:
    """Get the active market's tax profile."""
    profile = service.get_tax_profile()
    if profile is None:
        raise HTTPException(status_code=400, detail="No market configured")
    return {"tax_profile": profile}


@router.post("/market/tax/generate/{country_code}")
async def generate_tax_profile(
    country_code: str,
    _localhost: bool = Depends(require_localhost),
    service: MarketService = Depends(get_market_service),
) -> dict:
    """Generate a tax profile using AI for the given country.

    Calls the configured LLM to generate up-to-date tax rules.
    The generated profile is returned for user review — it is NOT
    automatically applied.

    Requires NVIDIA NIM or Ollama to be configured.
    """
    try:
        result = await service.generate_tax_profile(country_code.upper())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return result


@router.post("/market/tax/refresh")
async def refresh_tax_profile(
    _localhost: bool = Depends(require_localhost),
    service: MarketService = Depends(get_market_service),
) -> dict:
    """Refresh the active market's tax profile using AI.

    Generates a new profile and returns a diff against the current one.
    User must confirm changes before they are applied.
    """
    try:
        result = await service.refresh_tax_profile()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return result


@router.post("/market/tax/confirm")
async def confirm_tax_profile(
    body: TaxProfileConfirmation,
    _localhost: bool = Depends(require_localhost),
    service: MarketService = Depends(get_market_service),
) -> dict:
    """Confirm and apply a tax profile after user review.

    Called when the user clicks "Confirm" after reviewing AI-generated
    or manually edited tax rules.
    """
    try:
        result = service.confirm_tax_profile(body.tax_profile)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return result


# ── Charge Estimation (authenticated) ──────────────────────────────────────


@router.post("/market/estimate-charges")
async def estimate_charges(
    body: ChargeEstimateRequest,
    service: MarketService = Depends(get_market_service),
) -> dict:
    """Estimate transaction charges for a trade.

    Used by the order ticket to show estimated charges (STT, stamp duty,
    exchange fees, etc.) before the user confirms the order.

    Available to authenticated users (no localhost restriction).
    """
    result = service.estimate_charges(
        trade_value=body.trade_value,
        side=body.side,
        is_intraday=body.is_intraday,
        brokerage=body.brokerage,
    )
    if result is None:
        raise HTTPException(
            status_code=400,
            detail="No market configured. Complete setup first.",
        )
    return result
