"""Unit tests for screener API router endpoints."""

import io
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.screener import (
    router,
    get_screener_engine,
    get_db_pool,
)
from app.routers.auth_v2 import get_current_user_id, get_current_user_payload
from app.services.screener_service import (
    ScreenerEngine,
    ScreenerFilters,
    ScreenerPreset,
    ScreenerResult,
    ScreenerResultItem,
    Range,
    filters_to_dict,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

TEST_USER_ID = "test-user-screener-001"


def _create_test_app(
    engine: ScreenerEngine = None,
    db_pool=None,
    role: str = "TRADER",
) -> FastAPI:
    """Create a minimal FastAPI app with the screener router for testing."""
    app = FastAPI()
    app.include_router(router, prefix="/api/v2")

    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID
    app.dependency_overrides[get_current_user_payload] = lambda: {
        "sub": TEST_USER_ID,
        "email": "test@example.com",
        "role": role,
        "type": "access",
    }

    if engine is not None:
        app.dependency_overrides[get_screener_engine] = lambda: engine
    if db_pool is not None:
        app.dependency_overrides[get_db_pool] = lambda: db_pool

    return app


def _make_result_item(**overrides) -> ScreenerResultItem:
    """Create a ScreenerResultItem with sensible defaults."""
    defaults = dict(
        security_id=1,
        symbol="RELIANCE",
        company_name="Reliance Industries",
        exchange="NSE",
        sector="Energy",
        market_cap_category="large-cap",
        pe_ratio=Decimal("25.5"),
        pb_ratio=Decimal("2.1"),
        market_cap=Decimal("1500000000000"),
        dividend_yield=Decimal("0.5"),
        eps=Decimal("95.2"),
        roe=Decimal("12.3"),
        debt_to_equity=Decimal("0.4"),
        rsi_14=Decimal("55.0"),
        sma_50=Decimal("2400.0"),
        sma_200=Decimal("2300.0"),
        avg_volume_20d=5000000,
        price_change_1d=Decimal("1.2"),
    )
    defaults.update(overrides)
    return ScreenerResultItem(**defaults)


def _make_preset(**overrides) -> ScreenerPreset:
    """Create a ScreenerPreset with sensible defaults."""
    defaults = dict(
        id="preset-001",
        user_id=TEST_USER_ID,
        name="My Preset",
        filters=ScreenerFilters(pe_ratio=Range(max=20.0)),
        is_prebuilt=False,
        created_at=datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return ScreenerPreset(**defaults)


# ── Screener Search Tests ────────────────────────────────────────────────────


class TestScreenerSearch:
    def test_search_returns_results(self):
        mock_engine = AsyncMock(spec=ScreenerEngine)
        mock_engine.screen = AsyncMock(return_value=ScreenerResult(
            items=[_make_result_item(security_id=1, symbol="RELIANCE"),
                   _make_result_item(security_id=2, symbol="TCS")],
            total=2, page=1, page_size=50, total_pages=1,
        ))

        app = _create_test_app(engine=mock_engine)
        client = TestClient(app)
        resp = client.post("/api/v2/screener/search", json={
            "pe_ratio": {"min": 5, "max": 30},
            "sort_by": "market_cap",
            "order": "desc",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2
        assert data["items"][0]["symbol"] == "RELIANCE"
        assert data["items"][1]["symbol"] == "TCS"

    def test_search_empty_results(self):
        mock_engine = AsyncMock(spec=ScreenerEngine)
        mock_engine.screen = AsyncMock(return_value=ScreenerResult())

        app = _create_test_app(engine=mock_engine)
        client = TestClient(app)
        resp = client.post("/api/v2/screener/search", json={})

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_search_with_pagination(self):
        mock_engine = AsyncMock(spec=ScreenerEngine)
        mock_engine.screen = AsyncMock(return_value=ScreenerResult(
            items=[], total=200, page=3, page_size=20, total_pages=10,
        ))

        app = _create_test_app(engine=mock_engine)
        client = TestClient(app)
        resp = client.post("/api/v2/screener/search", json={
            "page": 3, "page_size": 20,
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 3
        assert data["page_size"] == 20
        assert data["total_pages"] == 10

    def test_search_with_multiple_filters(self):
        mock_engine = AsyncMock(spec=ScreenerEngine)
        mock_engine.screen = AsyncMock(return_value=ScreenerResult(
            items=[_make_result_item()], total=1, page=1, page_size=50, total_pages=1,
        ))

        app = _create_test_app(engine=mock_engine)
        client = TestClient(app)
        resp = client.post("/api/v2/screener/search", json={
            "pe_ratio": {"min": 5, "max": 30},
            "dividend_yield": {"min": 2.0},
            "sector": "Energy",
            "market_cap_category": "large-cap",
            "rsi_14": {"min": 30, "max": 70},
        })

        assert resp.status_code == 200
        # Verify the engine was called with correct filters
        call_args = mock_engine.screen.call_args
        filters = call_args.kwargs["filters"]
        assert filters.pe_ratio.min == 5
        assert filters.pe_ratio.max == 30
        assert filters.dividend_yield.min == 2.0
        assert filters.sector == "Energy"
        assert filters.rsi_14.min == 30
        assert filters.rsi_14.max == 70

    def test_search_service_not_initialized(self):
        app = FastAPI()
        app.include_router(router, prefix="/api/v2")
        app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID
        app.dependency_overrides[get_current_user_payload] = lambda: {
            "sub": TEST_USER_ID, "email": "t@t.com", "role": "TRADER", "type": "access",
        }
        client = TestClient(app)
        resp = client.post("/api/v2/screener/search", json={})
        assert resp.status_code == 503


# ── Preset Tests ─────────────────────────────────────────────────────────────


class TestGetPresets:
    def test_get_presets_returns_list(self):
        mock_engine = AsyncMock(spec=ScreenerEngine)
        mock_engine.get_user_presets = AsyncMock(return_value=[
            _make_preset(id="p1", name="Preset A"),
            _make_preset(id="p2", name="Preset B"),
        ])

        app = _create_test_app(engine=mock_engine)
        client = TestClient(app)
        resp = client.get("/api/v2/screener/presets")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert data["presets"][0]["name"] == "Preset A"
        assert data["presets"][1]["name"] == "Preset B"

    def test_get_presets_empty(self):
        mock_engine = AsyncMock(spec=ScreenerEngine)
        mock_engine.get_user_presets = AsyncMock(return_value=[])

        app = _create_test_app(engine=mock_engine)
        client = TestClient(app)
        resp = client.get("/api/v2/screener/presets")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["presets"] == []


class TestSavePreset:
    def test_save_preset_success(self):
        mock_engine = AsyncMock(spec=ScreenerEngine)
        mock_engine.save_preset = AsyncMock(return_value=_make_preset(
            id="new-preset", name="My New Preset",
        ))

        app = _create_test_app(engine=mock_engine)
        client = TestClient(app)
        resp = client.post("/api/v2/screener/presets", json={
            "name": "My New Preset",
            "filters": {"pe_ratio": {"min": 5, "max": 25}},
        })

        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "My New Preset"
        assert data["id"] == "new-preset"

    def test_save_preset_limit_exceeded(self):
        mock_engine = AsyncMock(spec=ScreenerEngine)
        mock_engine.save_preset = AsyncMock(return_value=None)

        app = _create_test_app(engine=mock_engine)
        client = TestClient(app)
        resp = client.post("/api/v2/screener/presets", json={
            "name": "Overflow Preset",
            "filters": {},
        })

        assert resp.status_code == 400
        assert "Maximum 10" in resp.json()["detail"]

    def test_save_preset_missing_name(self):
        mock_engine = AsyncMock(spec=ScreenerEngine)
        app = _create_test_app(engine=mock_engine)
        client = TestClient(app)
        resp = client.post("/api/v2/screener/presets", json={
            "filters": {},
        })
        assert resp.status_code == 422


class TestDeletePreset:
    def test_delete_preset_success(self):
        mock_engine = AsyncMock(spec=ScreenerEngine)
        mock_engine.delete_preset = AsyncMock(return_value=True)

        app = _create_test_app(engine=mock_engine)
        client = TestClient(app)
        resp = client.delete("/api/v2/screener/presets/preset-001")

        assert resp.status_code == 200
        assert "deleted" in resp.json()["message"].lower()

    def test_delete_preset_not_found(self):
        mock_engine = AsyncMock(spec=ScreenerEngine)
        mock_engine.delete_preset = AsyncMock(return_value=False)

        app = _create_test_app(engine=mock_engine)
        client = TestClient(app)
        resp = client.delete("/api/v2/screener/presets/nonexistent")

        assert resp.status_code == 404


# ── Templates Tests ──────────────────────────────────────────────────────────


class TestGetTemplates:
    def test_get_templates_returns_prebuilt(self):
        mock_engine = AsyncMock(spec=ScreenerEngine)
        mock_engine.get_prebuilt_templates = MagicMock(return_value=[
            ScreenerPreset(name="High Dividend Yield", filters=ScreenerFilters(dividend_yield=Range(min=3.0)), is_prebuilt=True),
            ScreenerPreset(name="Momentum Stocks", filters=ScreenerFilters(price_change_1m=Range(min=5.0)), is_prebuilt=True),
        ])

        app = _create_test_app(engine=mock_engine)
        client = TestClient(app)
        resp = client.get("/api/v2/screener/templates")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert data["templates"][0]["name"] == "High Dividend Yield"
        assert data["templates"][0]["is_prebuilt"] is True
        assert data["templates"][1]["name"] == "Momentum Stocks"


# ── Export CSV Tests ─────────────────────────────────────────────────────────


class TestExportCSV:
    def test_export_csv_returns_file(self):
        mock_engine = AsyncMock(spec=ScreenerEngine)
        csv_content = b"Symbol,Company Name\nRELIANCE,Reliance Industries\n"
        mock_engine.export_csv = AsyncMock(return_value=csv_content)

        app = _create_test_app(engine=mock_engine)
        client = TestClient(app)
        resp = client.get("/api/v2/screener/export")

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "text/csv; charset=utf-8"
        assert "attachment" in resp.headers.get("content-disposition", "")
        assert b"RELIANCE" in resp.content

    def test_export_csv_with_filters(self):
        mock_engine = AsyncMock(spec=ScreenerEngine)
        mock_engine.export_csv = AsyncMock(return_value=b"Symbol\n")

        app = _create_test_app(engine=mock_engine)
        client = TestClient(app)
        resp = client.get(
            "/api/v2/screener/export"
            "?pe_ratio_min=5&pe_ratio_max=30&sector=Energy&sort_by=pe_ratio&order=asc"
        )

        assert resp.status_code == 200
        call_args = mock_engine.export_csv.call_args
        filters = call_args.args[0] if call_args.args else call_args.kwargs.get("filters")
        assert filters.pe_ratio is not None
        assert filters.pe_ratio.min == 5.0
        assert filters.pe_ratio.max == 30.0
        assert filters.sector == "Energy"

    def test_export_csv_empty(self):
        mock_engine = AsyncMock(spec=ScreenerEngine)
        mock_engine.export_csv = AsyncMock(return_value=b"")

        app = _create_test_app(engine=mock_engine)
        client = TestClient(app)
        resp = client.get("/api/v2/screener/export")

        assert resp.status_code == 200


# ── Stock Detail Tests ───────────────────────────────────────────────────────


class TestStockDetail:
    def _make_mock_db_pool(self, row=None):
        """Create a mock db_pool that returns a given row from fetchrow."""
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=row)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=mock_conn)
        return mock_pool

    def test_stock_detail_found(self):
        row = {
            "id": 42, "symbol": "INFY", "company_name": "Infosys Limited",
            "exchange": "NSE", "sector": "IT/Technology", "industry": "IT Services",
            "market_cap_category": "large-cap", "listing_date": None,
            "face_value": Decimal("5"), "status": "ACTIVE",
            "pe_ratio": Decimal("28.5"), "pb_ratio": Decimal("7.2"),
            "market_cap": Decimal("600000000000"), "dividend_yield": Decimal("2.1"),
            "eps": Decimal("55.3"), "roe": Decimal("30.1"),
            "debt_to_equity": Decimal("0.1"),
            "revenue_growth_1y": Decimal("12.5"), "revenue_growth_3y": Decimal("10.0"),
            "profit_growth_1y": Decimal("15.0"), "profit_growth_3y": Decimal("11.0"),
            "return_1y": Decimal("20.0"), "cagr_3y": Decimal("15.0"),
            "cagr_5y": Decimal("12.0"),
            "high_52w": Decimal("1800"), "low_52w": Decimal("1200"),
            "rsi_14": Decimal("60.0"), "sma_50": Decimal("1600"),
            "sma_200": Decimal("1500"), "avg_volume_20d": 3000000,
            "price_change_1d": Decimal("1.5"), "price_change_1w": Decimal("3.0"),
            "price_change_1m": Decimal("5.0"), "price_change_3m": Decimal("8.0"),
            "price_change_6m": Decimal("12.0"), "price_change_1y": Decimal("20.0"),
            "price_change_3y": Decimal("45.0"), "price_change_5y": Decimal("80.0"),
        }
        mock_pool = self._make_mock_db_pool(row=row)
        mock_engine = AsyncMock(spec=ScreenerEngine)

        app = _create_test_app(engine=mock_engine, db_pool=mock_pool)
        client = TestClient(app)
        resp = client.get("/api/v2/stocks/INFY/detail")

        assert resp.status_code == 200
        data = resp.json()
        assert data["security_id"] == 42
        assert data["symbol"] == "INFY"
        assert data["company_name"] == "Infosys Limited"
        assert data["sector"] == "IT/Technology"
        assert data["pe_ratio"] == "28.5"
        assert data["rsi_14"] == "60.0"
        assert data["avg_volume_20d"] == 3000000

    def test_stock_detail_not_found(self):
        mock_pool = self._make_mock_db_pool(row=None)
        mock_engine = AsyncMock(spec=ScreenerEngine)

        app = _create_test_app(engine=mock_engine, db_pool=mock_pool)
        client = TestClient(app)
        resp = client.get("/api/v2/stocks/NOSYMBOL/detail")

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"]

    def test_stock_detail_db_not_initialized(self):
        mock_engine = AsyncMock(spec=ScreenerEngine)
        app = FastAPI()
        app.include_router(router, prefix="/api/v2")
        app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID
        app.dependency_overrides[get_current_user_payload] = lambda: {
            "sub": TEST_USER_ID, "email": "t@t.com", "role": "TRADER", "type": "access",
        }
        app.dependency_overrides[get_screener_engine] = lambda: mock_engine
        client = TestClient(app)
        resp = client.get("/api/v2/stocks/INFY/detail")
        assert resp.status_code == 503


# ── RBAC Tests ───────────────────────────────────────────────────────────────


class TestScreenerRBAC:
    def test_viewer_denied_search(self):
        mock_engine = AsyncMock(spec=ScreenerEngine)
        app = _create_test_app(engine=mock_engine, role="VIEWER")
        client = TestClient(app)
        resp = client.post("/api/v2/screener/search", json={})
        assert resp.status_code == 403

    def test_viewer_denied_presets(self):
        mock_engine = AsyncMock(spec=ScreenerEngine)
        app = _create_test_app(engine=mock_engine, role="VIEWER")
        client = TestClient(app)
        resp = client.get("/api/v2/screener/presets")
        assert resp.status_code == 403

    def test_viewer_denied_save_preset(self):
        mock_engine = AsyncMock(spec=ScreenerEngine)
        app = _create_test_app(engine=mock_engine, role="VIEWER")
        client = TestClient(app)
        resp = client.post("/api/v2/screener/presets", json={"name": "x", "filters": {}})
        assert resp.status_code == 403

    def test_viewer_denied_delete_preset(self):
        mock_engine = AsyncMock(spec=ScreenerEngine)
        app = _create_test_app(engine=mock_engine, role="VIEWER")
        client = TestClient(app)
        resp = client.delete("/api/v2/screener/presets/p1")
        assert resp.status_code == 403

    def test_viewer_denied_templates(self):
        mock_engine = AsyncMock(spec=ScreenerEngine)
        app = _create_test_app(engine=mock_engine, role="VIEWER")
        client = TestClient(app)
        resp = client.get("/api/v2/screener/templates")
        assert resp.status_code == 403

    def test_viewer_denied_export(self):
        mock_engine = AsyncMock(spec=ScreenerEngine)
        app = _create_test_app(engine=mock_engine, role="VIEWER")
        client = TestClient(app)
        resp = client.get("/api/v2/screener/export")
        assert resp.status_code == 403

    def test_viewer_denied_stock_detail(self):
        mock_engine = AsyncMock(spec=ScreenerEngine)
        mock_pool = MagicMock()
        app = _create_test_app(engine=mock_engine, db_pool=mock_pool, role="VIEWER")
        client = TestClient(app)
        resp = client.get("/api/v2/stocks/INFY/detail")
        assert resp.status_code == 403

    def test_admin_allowed_search(self):
        mock_engine = AsyncMock(spec=ScreenerEngine)
        mock_engine.screen = AsyncMock(return_value=ScreenerResult())
        app = _create_test_app(engine=mock_engine, role="ADMIN")
        client = TestClient(app)
        resp = client.post("/api/v2/screener/search", json={})
        assert resp.status_code == 200

    def test_admin_allowed_templates(self):
        mock_engine = AsyncMock(spec=ScreenerEngine)
        mock_engine.get_prebuilt_templates = MagicMock(return_value=[])
        app = _create_test_app(engine=mock_engine, role="ADMIN")
        client = TestClient(app)
        resp = client.get("/api/v2/screener/templates")
        assert resp.status_code == 200
