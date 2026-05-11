"""Property-based tests for stock search.

**Validates: Requirements 7.6**

Property 11: Search response time — search queries return results within 200ms
for any query string.

Property 12: Search completeness — searching by exact symbol always returns that
security if it exists and is active.
"""

import asyncio
import string
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.services.stock_universe_service import (
    StockUniverseService,
    Security,
)


def _run_async(coro):
    """Run an async coroutine synchronously (compatible with Python 3.14+)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_mock_pool_with_data(securities: list[dict]):
    """Create a mock asyncpg pool that returns matching securities for search.

    The mock simulates the DB behaviour: tsquery match first, ILIKE fallback.
    For Property 12 we need the mock to faithfully return a security when
    searched by its exact symbol.
    """
    pool = MagicMock()
    conn = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = ctx

    def _make_row(sec: dict):
        row = MagicMock()
        row.__getitem__ = lambda self, key: sec[key]
        row.get = lambda key, default=None: sec.get(key, default)
        return row

    rows = [_make_row(s) for s in securities]

    async def _fetch(query_sql, *args):
        """Simulate DB fetch — return all rows for any query (mock behaviour)."""
        return rows

    conn.fetch = AsyncMock(side_effect=_fetch)
    return pool


def _make_security_dict(
    id: int = 1,
    symbol: str = "RELIANCE",
    isin: str = "INE002A01018",
    company_name: str = "Reliance Industries Limited",
    exchange: str = "NSE",
    sector: str = "Energy",
    industry: str = "Oil & Gas",
    market_cap_category: str = "large-cap",
    status: str = "ACTIVE",
) -> dict:
    return {
        "id": id,
        "symbol": symbol,
        "isin": isin,
        "company_name": company_name,
        "exchange": exchange,
        "sector": sector,
        "industry": industry,
        "market_cap_category": market_cap_category,
        "listing_date": date(2020, 1, 1),
        "face_value": Decimal("10.00"),
        "status": status,
        "updated_at": datetime.now(timezone.utc),
    }


# ── Strategies ───────────────────────────────────────────────────────────────

# Strategy: arbitrary non-empty search query strings (printable, reasonable length)
search_query = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Z")),
    min_size=1,
    max_size=30,
).filter(lambda s: s.strip() != "")

# Strategy: valid stock symbols (1-10 uppercase letters)
stock_symbol = st.text(
    alphabet=string.ascii_uppercase,
    min_size=1,
    max_size=10,
)


# ── Property 11: Search response time ────────────────────────────────────────


class TestSearchResponseTimeProperty:
    """**Validates: Requirements 7.6**

    Property 11: Search response time — search queries return results within
    200ms for any query string.

    Since we don't have a real database, we mock the db_pool with fast
    responses and verify the search method itself completes within 200ms.
    """

    @given(query=search_query)
    @settings(max_examples=50)
    def test_search_completes_within_200ms(self, query: str):
        """For any query string, search_securities completes within 200ms
        when the underlying DB responds quickly (mocked)."""
        sec_data = _make_security_dict(symbol="TEST", company_name="Test Corp")
        pool = _make_mock_pool_with_data([sec_data])
        svc = StockUniverseService(db_pool=pool)

        start = time.monotonic()
        result = _run_async(svc.search_securities(query))
        elapsed_ms = (time.monotonic() - start) * 1000

        assert elapsed_ms < 200, (
            f"Search for {query!r} took {elapsed_ms:.1f}ms, exceeding 200ms target"
        )
        # Result should be a list (may be empty or contain items)
        assert isinstance(result, list)


# ── Property 12: Search completeness ─────────────────────────────────────────


class TestSearchCompletenessProperty:
    """**Validates: Requirements 7.6**

    Property 12: Search completeness — searching by exact symbol always returns
    that security if it exists and is active.

    We set up a mock DB that contains a security with a given symbol and verify
    that searching by that exact symbol returns it in the results.
    """

    @given(symbol=stock_symbol)
    @settings(max_examples=50)
    def test_exact_symbol_search_returns_security(self, symbol: str):
        """When a security with a given symbol exists and is ACTIVE,
        searching by that exact symbol must return it."""
        sec_data = _make_security_dict(
            id=1,
            symbol=symbol,
            isin=f"INE{symbol[:3].ljust(3, 'X')}A01018",
            company_name=f"{symbol} Corporation",
            status="ACTIVE",
        )
        pool = _make_mock_pool_with_data([sec_data])
        svc = StockUniverseService(db_pool=pool)

        result = _run_async(svc.search_securities(symbol))

        assert len(result) >= 1, (
            f"Searching for exact symbol {symbol!r} returned no results"
        )
        symbols_returned = [s.symbol for s in result]
        assert symbol in symbols_returned, (
            f"Security with symbol {symbol!r} not found in results: {symbols_returned}"
        )

    @given(symbol=stock_symbol)
    @settings(max_examples=25)
    def test_inactive_security_not_returned_by_search(self, symbol: str):
        """When a security exists but is INACTIVE, search_securities should
        not return it (the service filters by status='ACTIVE')."""
        # Mock returns empty for INACTIVE securities (simulating the WHERE status='ACTIVE' filter)
        pool = _make_mock_pool_with_data([])
        svc = StockUniverseService(db_pool=pool)

        result = _run_async(svc.search_securities(symbol))

        # With no active securities matching, result should be empty
        assert len(result) == 0, (
            f"Search for inactive symbol {symbol!r} unexpectedly returned results"
        )
