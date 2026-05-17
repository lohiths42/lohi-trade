"""Unit tests for stock universe and sector classification API router endpoints."""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from app.routers.auth_v2 import get_current_user_id, get_current_user_payload
from app.routers.stock_universe import (
    get_sector_service,
    get_stock_universe_service,
    router,
)
from app.services.sector_service import (
    SectorAggregate,
    SectorSecurity,
    SectorService,
    SecurityGainerLoser,
)
from app.services.stock_universe_service import (
    PaginatedResult,
    Security,
    StockUniverseService,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ── Helpers ──────────────────────────────────────────────────────────────────

TEST_USER_ID = "test-user-stock-001"


def _create_test_app(
    stock_svc: StockUniverseService = None,
    sector_svc: SectorService = None,
    role: str = "TRADER",
) -> FastAPI:
    """Create a minimal FastAPI app with the stock universe router for testing."""
    app = FastAPI()
    app.include_router(router, prefix="/api/v2")

    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID
    app.dependency_overrides[get_current_user_payload] = lambda: {
        "sub": TEST_USER_ID,
        "email": "test@example.com",
        "role": role,
        "type": "access",
    }

    if stock_svc is not None:
        app.dependency_overrides[get_stock_universe_service] = lambda: stock_svc
    if sector_svc is not None:
        app.dependency_overrides[get_sector_service] = lambda: sector_svc

    return app


def _make_security(**overrides) -> Security:
    """Create a Security with sensible defaults."""
    defaults = dict(
        id=1,
        symbol="RELIANCE",
        isin="INE002A01018",
        company_name="Reliance Industries Limited",
        exchange="NSE",
        sector="Energy",
        industry="Oil & Gas",
        market_cap_category="large-cap",
        listing_date=date(1977, 1, 1),
        face_value=Decimal("10"),
        status="ACTIVE",
        updated_at=None,
    )
    defaults.update(overrides)
    return Security(**defaults)


# ── Search Tests ─────────────────────────────────────────────────────────────


class TestSearchStocks:
    def test_search_returns_results(self):
        mock_svc = AsyncMock(spec=StockUniverseService)
        mock_svc.search_securities = AsyncMock(
            return_value=[
                _make_security(id=1, symbol="RELIANCE", company_name="Reliance Industries"),
                _make_security(
                    id=2, symbol="RIL", company_name="Reliance Infra", isin="INE036A01016"
                ),
            ]
        )

        app = _create_test_app(stock_svc=mock_svc)
        client = TestClient(app)
        resp = client.get("/api/v2/stocks/search?q=reliance")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert data["results"][0]["symbol"] == "RELIANCE"
        assert data["results"][1]["symbol"] == "RIL"

    def test_search_empty_results(self):
        mock_svc = AsyncMock(spec=StockUniverseService)
        mock_svc.search_securities = AsyncMock(return_value=[])

        app = _create_test_app(stock_svc=mock_svc)
        client = TestClient(app)
        resp = client.get("/api/v2/stocks/search?q=nonexistent")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["results"] == []

    def test_search_requires_query_param(self):
        mock_svc = AsyncMock(spec=StockUniverseService)
        app = _create_test_app(stock_svc=mock_svc)
        client = TestClient(app)
        resp = client.get("/api/v2/stocks/search")
        assert resp.status_code == 422

    def test_search_with_custom_limit(self):
        mock_svc = AsyncMock(spec=StockUniverseService)
        mock_svc.search_securities = AsyncMock(
            return_value=[
                _make_security(id=1, symbol="TCS"),
            ]
        )

        app = _create_test_app(stock_svc=mock_svc)
        client = TestClient(app)
        resp = client.get("/api/v2/stocks/search?q=TCS&limit=5")

        assert resp.status_code == 200
        mock_svc.search_securities.assert_called_once_with("TCS", limit=5)

    def test_search_service_not_initialized(self):
        app = FastAPI()
        app.include_router(router, prefix="/api/v2")
        app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID
        app.dependency_overrides[get_current_user_payload] = lambda: {
            "sub": TEST_USER_ID,
            "email": "t@t.com",
            "role": "TRADER",
            "type": "access",
        }
        client = TestClient(app)
        resp = client.get("/api/v2/stocks/search?q=test")
        assert resp.status_code == 503


# ── List Stocks Tests ────────────────────────────────────────────────────────


class TestListStocks:
    def test_list_default_pagination(self):
        mock_svc = AsyncMock(spec=StockUniverseService)
        mock_svc.list_securities = AsyncMock(
            return_value=PaginatedResult(
                items=[_make_security(id=1, symbol="INFY"), _make_security(id=2, symbol="TCS")],
                total=2,
                page=1,
                page_size=50,
                total_pages=1,
            )
        )

        app = _create_test_app(stock_svc=mock_svc)
        client = TestClient(app)
        resp = client.get("/api/v2/stocks")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["page"] == 1
        assert data["page_size"] == 50
        assert len(data["items"]) == 2

    def test_list_with_filters(self):
        mock_svc = AsyncMock(spec=StockUniverseService)
        mock_svc.list_securities = AsyncMock(
            return_value=PaginatedResult(
                items=[_make_security(id=1, symbol="HDFCBANK", sector="Banking & Finance")],
                total=1,
                page=1,
                page_size=50,
                total_pages=1,
            )
        )

        app = _create_test_app(stock_svc=mock_svc)
        client = TestClient(app)
        resp = client.get(
            "/api/v2/stocks?exchange=NSE&sector=Banking+%26+Finance&market_cap_category=large-cap&status=ACTIVE"
        )

        assert resp.status_code == 200
        mock_svc.list_securities.assert_called_once_with(
            exchange="NSE",
            sector="Banking & Finance",
            market_cap_category="large-cap",
            status="ACTIVE",
            page=1,
            page_size=50,
        )

    def test_list_with_pagination(self):
        mock_svc = AsyncMock(spec=StockUniverseService)
        mock_svc.list_securities = AsyncMock(
            return_value=PaginatedResult(
                items=[],
                total=100,
                page=3,
                page_size=10,
                total_pages=10,
            )
        )

        app = _create_test_app(stock_svc=mock_svc)
        client = TestClient(app)
        resp = client.get("/api/v2/stocks?page=3&page_size=10")

        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 3
        assert data["page_size"] == 10
        assert data["total_pages"] == 10

    def test_list_empty(self):
        mock_svc = AsyncMock(spec=StockUniverseService)
        mock_svc.list_securities = AsyncMock(return_value=PaginatedResult())

        app = _create_test_app(stock_svc=mock_svc)
        client = TestClient(app)
        resp = client.get("/api/v2/stocks")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []


# ── Get Stock by Symbol Tests ────────────────────────────────────────────────


class TestGetStockBySymbol:
    def test_get_existing_stock(self):
        mock_svc = AsyncMock(spec=StockUniverseService)
        mock_svc.get_security_by_symbol = AsyncMock(
            return_value=_make_security(
                id=1,
                symbol="INFY",
                company_name="Infosys Limited",
            )
        )

        app = _create_test_app(stock_svc=mock_svc)
        client = TestClient(app)
        resp = client.get("/api/v2/stocks/INFY")

        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "INFY"
        assert data["company_name"] == "Infosys Limited"

    def test_get_nonexistent_stock(self):
        mock_svc = AsyncMock(spec=StockUniverseService)
        mock_svc.get_security_by_symbol = AsyncMock(return_value=None)

        app = _create_test_app(stock_svc=mock_svc)
        client = TestClient(app)
        resp = client.get("/api/v2/stocks/NOSYMBOL")

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"]

    def test_get_stock_includes_all_fields(self):
        mock_svc = AsyncMock(spec=StockUniverseService)
        mock_svc.get_security_by_symbol = AsyncMock(
            return_value=_make_security(
                id=42,
                symbol="RELIANCE",
                isin="INE002A01018",
                company_name="Reliance Industries Limited",
                exchange="BOTH",
                sector="Energy",
                industry="Oil & Gas",
                market_cap_category="large-cap",
                listing_date=date(1977, 1, 1),
                face_value=Decimal("10"),
                status="ACTIVE",
            )
        )

        app = _create_test_app(stock_svc=mock_svc)
        client = TestClient(app)
        resp = client.get("/api/v2/stocks/RELIANCE")

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == 42
        assert data["isin"] == "INE002A01018"
        assert data["exchange"] == "BOTH"
        assert data["sector"] == "Energy"
        assert data["market_cap_category"] == "large-cap"
        assert data["listing_date"] == "1977-01-01"
        assert data["face_value"] == "10"


# ── Sector List Tests ────────────────────────────────────────────────────────


class TestListSectors:
    def test_list_all_sectors(self):
        mock_svc = MagicMock(spec=SectorService)
        mock_svc.get_sectors = MagicMock(
            return_value=[
                "Pharma",
                "IT/Technology",
                "AI/Deep Tech",
                "Metals & Mining",
                "Banking & Finance",
                "FMCG",
                "Energy",
                "Automobile",
                "Telecom",
                "Real Estate",
                "Infrastructure",
                "Chemicals",
                "Media & Entertainment",
                "Insurance",
                "Miscellaneous",
            ]
        )

        app = _create_test_app(sector_svc=mock_svc)
        client = TestClient(app)
        resp = client.get("/api/v2/sectors")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 15
        assert "Pharma" in data["sectors"]
        assert "Miscellaneous" in data["sectors"]


# ── Sector Aggregate Tests ───────────────────────────────────────────────────


class TestGetSectorAggregate:
    def test_aggregate_with_data(self):
        mock_svc = AsyncMock(spec=SectorService)
        mock_svc.get_sector_aggregate = AsyncMock(
            return_value=SectorAggregate(
                sector="Pharma",
                total_market_cap=Decimal("5000000000000"),
                stock_count=120,
                top_gainers=[
                    SecurityGainerLoser(
                        security_id=1,
                        symbol="SUNPHARMA",
                        company_name="Sun Pharma",
                        price_change_1d=Decimal("3.5"),
                        market_cap=Decimal("1200000000000"),
                    ),
                ],
                top_losers=[
                    SecurityGainerLoser(
                        security_id=2,
                        symbol="CIPLA",
                        company_name="Cipla Ltd",
                        price_change_1d=Decimal("-2.1"),
                        market_cap=Decimal("300000000000"),
                    ),
                ],
            )
        )

        app = _create_test_app(sector_svc=mock_svc)
        client = TestClient(app)
        resp = client.get("/api/v2/sectors/Pharma")

        assert resp.status_code == 200
        data = resp.json()
        assert data["sector"] == "Pharma"
        assert data["stock_count"] == 120
        assert len(data["top_gainers"]) == 1
        assert data["top_gainers"][0]["symbol"] == "SUNPHARMA"
        assert len(data["top_losers"]) == 1
        assert data["top_losers"][0]["symbol"] == "CIPLA"

    def test_aggregate_empty_sector(self):
        mock_svc = AsyncMock(spec=SectorService)
        mock_svc.get_sector_aggregate = AsyncMock(
            return_value=SectorAggregate(
                sector="Unknown",
                total_market_cap=Decimal("0"),
                stock_count=0,
                top_gainers=[],
                top_losers=[],
            )
        )

        app = _create_test_app(sector_svc=mock_svc)
        client = TestClient(app)
        resp = client.get("/api/v2/sectors/Unknown")

        assert resp.status_code == 200
        data = resp.json()
        assert data["stock_count"] == 0
        assert data["top_gainers"] == []
        assert data["top_losers"] == []


# ── Sub-Industries Tests ─────────────────────────────────────────────────────


class TestGetSectorSubIndustries:
    def test_sub_industries_for_known_sector(self):
        mock_svc = MagicMock(spec=SectorService)
        mock_svc.get_sub_industries = MagicMock(
            return_value=[
                "Private Banks",
                "PSU Banks",
                "NBFCs",
                "Microfinance",
                "Wealth Management",
            ]
        )

        app = _create_test_app(sector_svc=mock_svc)
        client = TestClient(app)
        resp = client.get("/api/v2/sectors/Banking & Finance/sub-industries")

        assert resp.status_code == 200
        data = resp.json()
        assert data["sector"] == "Banking & Finance"
        assert data["count"] == 5
        assert "Private Banks" in data["sub_industries"]

    def test_sub_industries_for_unknown_sector(self):
        mock_svc = MagicMock(spec=SectorService)
        mock_svc.get_sub_industries = MagicMock(return_value=[])

        app = _create_test_app(sector_svc=mock_svc)
        client = TestClient(app)
        resp = client.get("/api/v2/sectors/FakeSector/sub-industries")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["sub_industries"] == []


# ── Sector Stocks (Filter) Tests ─────────────────────────────────────────────


class TestGetSectorStocks:
    def test_filter_with_results(self):
        mock_svc = AsyncMock(spec=SectorService)
        mock_svc.filter_sector_securities = AsyncMock(
            return_value=(
                [
                    SectorSecurity(
                        security_id=1,
                        symbol="HDFCBANK",
                        company_name="HDFC Bank",
                        industry="Private Banks",
                        market_cap=Decimal("900000000000"),
                        pe_ratio=Decimal("22.5"),
                        dividend_yield=Decimal("1.2"),
                        price_change_1d=Decimal("1.5"),
                    ),
                    SectorSecurity(
                        security_id=2,
                        symbol="SBIN",
                        company_name="State Bank of India",
                        industry="PSU Banks",
                        market_cap=Decimal("600000000000"),
                        pe_ratio=Decimal("10.3"),
                        dividend_yield=Decimal("2.8"),
                        price_change_1d=Decimal("-0.5"),
                    ),
                ],
                2,
            )
        )

        app = _create_test_app(sector_svc=mock_svc)
        client = TestClient(app)
        resp = client.get("/api/v2/sectors/Banking & Finance/stocks?market_cap_min=100000000000")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2
        assert data["items"][0]["symbol"] == "HDFCBANK"
        assert data["items"][0]["pe_ratio"] == "22.5"
        assert data["items"][1]["symbol"] == "SBIN"

    def test_filter_empty_results(self):
        mock_svc = AsyncMock(spec=SectorService)
        mock_svc.filter_sector_securities = AsyncMock(return_value=([], 0))

        app = _create_test_app(sector_svc=mock_svc)
        client = TestClient(app)
        resp = client.get("/api/v2/sectors/Pharma/stocks")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_filter_with_all_params(self):
        mock_svc = AsyncMock(spec=SectorService)
        mock_svc.filter_sector_securities = AsyncMock(return_value=([], 0))

        app = _create_test_app(sector_svc=mock_svc)
        client = TestClient(app)
        resp = client.get(
            "/api/v2/sectors/Energy/stocks"
            "?market_cap_min=1000&market_cap_max=999999"
            "&pe_ratio_min=5&pe_ratio_max=30"
            "&dividend_yield_min=1&dividend_yield_max=10"
            "&page=2&page_size=25"
        )

        assert resp.status_code == 200
        # Verify the service was called with correct filter params
        call_args = mock_svc.filter_sector_securities.call_args
        assert call_args.kwargs["sector"] == "Energy"
        assert call_args.kwargs["page"] == 2
        assert call_args.kwargs["page_size"] == 25
        filters = call_args.kwargs["filters"]
        assert filters.market_cap_min == Decimal("1000")
        assert filters.market_cap_max == Decimal("999999")
        assert filters.pe_ratio_min == Decimal("5")
        assert filters.pe_ratio_max == Decimal("30")
        assert filters.dividend_yield_min == Decimal("1")
        assert filters.dividend_yield_max == Decimal("10")

    def test_filter_pagination_metadata(self):
        mock_svc = AsyncMock(spec=SectorService)
        mock_svc.filter_sector_securities = AsyncMock(return_value=([], 150))

        app = _create_test_app(sector_svc=mock_svc)
        client = TestClient(app)
        resp = client.get("/api/v2/sectors/FMCG/stocks?page=3&page_size=20")

        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 3
        assert data["page_size"] == 20
        assert data["total"] == 150


# ── RBAC Tests ───────────────────────────────────────────────────────────────


class TestStockUniverseRBAC:
    def test_viewer_denied_search(self):
        mock_svc = AsyncMock(spec=StockUniverseService)
        app = _create_test_app(stock_svc=mock_svc, role="VIEWER")
        client = TestClient(app)
        resp = client.get("/api/v2/stocks/search?q=test")
        assert resp.status_code == 403

    def test_viewer_denied_list(self):
        mock_svc = AsyncMock(spec=StockUniverseService)
        app = _create_test_app(stock_svc=mock_svc, role="VIEWER")
        client = TestClient(app)
        resp = client.get("/api/v2/stocks")
        assert resp.status_code == 403

    def test_viewer_denied_get_stock(self):
        mock_svc = AsyncMock(spec=StockUniverseService)
        app = _create_test_app(stock_svc=mock_svc, role="VIEWER")
        client = TestClient(app)
        resp = client.get("/api/v2/stocks/INFY")
        assert resp.status_code == 403

    def test_viewer_denied_sectors(self):
        mock_svc = MagicMock(spec=SectorService)
        app = _create_test_app(sector_svc=mock_svc, role="VIEWER")
        client = TestClient(app)
        resp = client.get("/api/v2/sectors")
        assert resp.status_code == 403

    def test_viewer_denied_sector_aggregate(self):
        mock_svc = AsyncMock(spec=SectorService)
        app = _create_test_app(sector_svc=mock_svc, role="VIEWER")
        client = TestClient(app)
        resp = client.get("/api/v2/sectors/Pharma")
        assert resp.status_code == 403

    def test_viewer_denied_sector_stocks(self):
        mock_svc = AsyncMock(spec=SectorService)
        app = _create_test_app(sector_svc=mock_svc, role="VIEWER")
        client = TestClient(app)
        resp = client.get("/api/v2/sectors/Pharma/stocks")
        assert resp.status_code == 403

    def test_admin_allowed_search(self):
        mock_svc = AsyncMock(spec=StockUniverseService)
        mock_svc.search_securities = AsyncMock(return_value=[])
        app = _create_test_app(stock_svc=mock_svc, role="ADMIN")
        client = TestClient(app)
        resp = client.get("/api/v2/stocks/search?q=test")
        assert resp.status_code == 200

    def test_admin_allowed_sectors(self):
        mock_svc = MagicMock(spec=SectorService)
        mock_svc.get_sectors = MagicMock(return_value=["Pharma"])
        app = _create_test_app(sector_svc=mock_svc, role="ADMIN")
        client = TestClient(app)
        resp = client.get("/api/v2/sectors")
        assert resp.status_code == 200
