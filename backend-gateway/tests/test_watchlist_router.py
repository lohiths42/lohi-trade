"""Unit tests for watchlist management API router endpoints."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

from app.routers.auth_v2 import get_current_user_id, get_current_user_payload
from app.routers.watchlist import (
    get_watchlist_service,
    router,
)
from app.services.watchlist_service import (
    SecurityPrice,
    Watchlist,
    WatchlistError,
    WatchlistService,
    WatchlistWithPrices,
)
from app.services.watchlist_service import (
    WatchlistItem as WLItem,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ── Helpers ──────────────────────────────────────────────────────────────────

TEST_USER_ID = "test-user-wl-001"
NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _create_test_app(
    wl_svc: WatchlistService = None,
    role: str = "TRADER",
) -> FastAPI:
    """Create a minimal FastAPI app with the watchlist router for testing."""
    app = FastAPI()
    app.include_router(router, prefix="/api/v2")

    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID
    app.dependency_overrides[get_current_user_payload] = lambda: {
        "sub": TEST_USER_ID,
        "email": "test@example.com",
        "role": role,
        "type": "access",
    }

    if wl_svc is not None:
        app.dependency_overrides[get_watchlist_service] = lambda: wl_svc

    return app


# ── Create Watchlist Tests ───────────────────────────────────────────────────


class TestCreateWatchlist:
    def test_successful_creation(self):
        mock_svc = AsyncMock(spec=WatchlistService)
        mock_svc.create_watchlist = AsyncMock(
            return_value=Watchlist(
                id="wl-001",
                user_id=TEST_USER_ID,
                name="My Stocks",
                is_prebuilt=False,
                sort_order=0,
                created_at=NOW,
            )
        )

        app = _create_test_app(wl_svc=mock_svc)
        client = TestClient(app)
        resp = client.post("/api/v2/watchlists", json={"name": "My Stocks"})

        assert resp.status_code == 201
        data = resp.json()
        assert data["watchlist"]["id"] == "wl-001"
        assert data["watchlist"]["name"] == "My Stocks"
        assert data["watchlist"]["is_prebuilt"] is False
        assert "created" in data["message"].lower()

    def test_create_empty_name_returns_400(self):
        mock_svc = AsyncMock(spec=WatchlistService)
        mock_svc.create_watchlist = AsyncMock(
            side_effect=WatchlistError("empty_name", "Watchlist name cannot be empty")
        )

        app = _create_test_app(wl_svc=mock_svc)
        client = TestClient(app)
        resp = client.post("/api/v2/watchlists", json={"name": ""})

        assert resp.status_code == 400
        assert "empty" in resp.json()["detail"].lower()

    def test_create_max_watchlists_returns_400(self):
        mock_svc = AsyncMock(spec=WatchlistService)
        mock_svc.create_watchlist = AsyncMock(
            side_effect=WatchlistError(
                "max_watchlists_reached", "Maximum 20 watchlists allowed per user"
            )
        )

        app = _create_test_app(wl_svc=mock_svc)
        client = TestClient(app)
        resp = client.post("/api/v2/watchlists", json={"name": "Too Many"})

        assert resp.status_code == 400
        assert "20" in resp.json()["detail"]

    def test_create_missing_name_returns_422(self):
        mock_svc = AsyncMock(spec=WatchlistService)
        app = _create_test_app(wl_svc=mock_svc)
        client = TestClient(app)
        resp = client.post("/api/v2/watchlists", json={})
        assert resp.status_code == 422

    def test_service_not_initialized_returns_503(self):
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
        resp = client.post("/api/v2/watchlists", json={"name": "Test"})
        assert resp.status_code == 503


# ── List Watchlists Tests ────────────────────────────────────────────────────


class TestListWatchlists:
    def test_list_with_watchlists(self):
        mock_svc = AsyncMock(spec=WatchlistService)
        mock_svc.get_user_watchlists = AsyncMock(
            return_value=[
                Watchlist(
                    id="wl-001", user_id=TEST_USER_ID, name="Tech", sort_order=0, created_at=NOW
                ),
                Watchlist(
                    id="wl-002", user_id=TEST_USER_ID, name="Banks", sort_order=1, created_at=NOW
                ),
            ]
        )

        app = _create_test_app(wl_svc=mock_svc)
        client = TestClient(app)
        resp = client.get("/api/v2/watchlists")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert data["watchlists"][0]["name"] == "Tech"
        assert data["watchlists"][1]["name"] == "Banks"

    def test_list_empty(self):
        mock_svc = AsyncMock(spec=WatchlistService)
        mock_svc.get_user_watchlists = AsyncMock(return_value=[])

        app = _create_test_app(wl_svc=mock_svc)
        client = TestClient(app)
        resp = client.get("/api/v2/watchlists")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["watchlists"] == []


# ── Get Watchlist Detail Tests ───────────────────────────────────────────────


class TestGetWatchlist:
    def test_get_with_securities(self):
        mock_svc = AsyncMock(spec=WatchlistService)
        mock_svc.get_watchlist_with_prices = AsyncMock(
            return_value=WatchlistWithPrices(
                id="wl-001",
                name="Tech",
                is_prebuilt=False,
                securities=[
                    SecurityPrice(
                        symbol="TCS",
                        company_name="TCS Ltd",
                        ltp=3500.0,
                        change_percent=1.5,
                        volume=100000,
                        sort_order=0,
                    ),
                    SecurityPrice(
                        symbol="INFY",
                        company_name="Infosys",
                        ltp=1500.0,
                        change_percent=-0.5,
                        volume=200000,
                        sort_order=1,
                    ),
                ],
            )
        )

        app = _create_test_app(wl_svc=mock_svc)
        client = TestClient(app)
        resp = client.get("/api/v2/watchlists/wl-001")

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "wl-001"
        assert data["name"] == "Tech"
        assert len(data["securities"]) == 2
        assert data["securities"][0]["symbol"] == "TCS"
        assert data["securities"][0]["ltp"] == 3500.0
        assert data["securities"][1]["symbol"] == "INFY"

    def test_get_not_found_returns_404(self):
        mock_svc = AsyncMock(spec=WatchlistService)
        mock_svc.get_watchlist_with_prices = AsyncMock(
            side_effect=WatchlistError("watchlist_not_found", "Watchlist not found")
        )

        app = _create_test_app(wl_svc=mock_svc)
        client = TestClient(app)
        resp = client.get("/api/v2/watchlists/nonexistent")

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()


# ── Rename Watchlist Tests ───────────────────────────────────────────────────


class TestRenameWatchlist:
    def test_rename_success(self):
        mock_svc = AsyncMock(spec=WatchlistService)
        mock_svc.rename_watchlist = AsyncMock(
            return_value=Watchlist(
                id="wl-001",
                user_id=TEST_USER_ID,
                name="Renamed",
                is_prebuilt=False,
                sort_order=0,
                created_at=NOW,
            )
        )

        app = _create_test_app(wl_svc=mock_svc)
        client = TestClient(app)
        resp = client.put("/api/v2/watchlists/wl-001", json={"name": "Renamed"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["watchlist"]["name"] == "Renamed"
        assert "renamed" in data["message"].lower()

    def test_rename_not_found_returns_400(self):
        mock_svc = AsyncMock(spec=WatchlistService)
        mock_svc.rename_watchlist = AsyncMock(
            side_effect=WatchlistError("watchlist_not_found", "Watchlist not found")
        )

        app = _create_test_app(wl_svc=mock_svc)
        client = TestClient(app)
        resp = client.put("/api/v2/watchlists/nonexistent", json={"name": "New"})

        assert resp.status_code == 400

    def test_rename_empty_name_returns_400(self):
        mock_svc = AsyncMock(spec=WatchlistService)
        mock_svc.rename_watchlist = AsyncMock(
            side_effect=WatchlistError("empty_name", "Watchlist name cannot be empty")
        )

        app = _create_test_app(wl_svc=mock_svc)
        client = TestClient(app)
        resp = client.put("/api/v2/watchlists/wl-001", json={"name": ""})

        assert resp.status_code == 400


# ── Delete Watchlist Tests ───────────────────────────────────────────────────


class TestDeleteWatchlist:
    def test_delete_success(self):
        mock_svc = AsyncMock(spec=WatchlistService)
        mock_svc.delete_watchlist = AsyncMock(return_value=True)

        app = _create_test_app(wl_svc=mock_svc)
        client = TestClient(app)
        resp = client.delete("/api/v2/watchlists/wl-001")

        assert resp.status_code == 200
        assert "deleted" in resp.json()["message"].lower()

    def test_delete_not_found_returns_400(self):
        mock_svc = AsyncMock(spec=WatchlistService)
        mock_svc.delete_watchlist = AsyncMock(
            side_effect=WatchlistError("watchlist_not_found", "Watchlist not found")
        )

        app = _create_test_app(wl_svc=mock_svc)
        client = TestClient(app)
        resp = client.delete("/api/v2/watchlists/nonexistent")

        assert resp.status_code == 400


# ── Add Security Tests ───────────────────────────────────────────────────────


class TestAddSecurity:
    def test_add_success(self):
        mock_svc = AsyncMock(spec=WatchlistService)
        mock_svc.add_security = AsyncMock(
            return_value=WLItem(
                id="item-001",
                watchlist_id="wl-001",
                security_id=42,
                symbol="RELIANCE",
                company_name="Reliance Industries",
                sort_order=0,
                added_at=NOW,
            )
        )

        app = _create_test_app(wl_svc=mock_svc)
        client = TestClient(app)
        resp = client.post("/api/v2/watchlists/wl-001/securities", json={"symbol": "RELIANCE"})

        assert resp.status_code == 201
        data = resp.json()
        assert data["symbol"] == "RELIANCE"
        assert data["watchlist_id"] == "wl-001"
        assert "added" in data["message"].lower()

    def test_add_security_not_found_returns_400(self):
        mock_svc = AsyncMock(spec=WatchlistService)
        mock_svc.add_security = AsyncMock(
            side_effect=WatchlistError("security_not_found", "Security 'FAKE' not found")
        )

        app = _create_test_app(wl_svc=mock_svc)
        client = TestClient(app)
        resp = client.post("/api/v2/watchlists/wl-001/securities", json={"symbol": "FAKE"})

        assert resp.status_code == 400
        assert "not found" in resp.json()["detail"].lower()

    def test_add_duplicate_returns_400(self):
        mock_svc = AsyncMock(spec=WatchlistService)
        mock_svc.add_security = AsyncMock(
            side_effect=WatchlistError(
                "duplicate_security", "Security 'TCS' is already in this watchlist"
            )
        )

        app = _create_test_app(wl_svc=mock_svc)
        client = TestClient(app)
        resp = client.post("/api/v2/watchlists/wl-001/securities", json={"symbol": "TCS"})

        assert resp.status_code == 400
        assert "already" in resp.json()["detail"].lower()

    def test_add_max_securities_returns_400(self):
        mock_svc = AsyncMock(spec=WatchlistService)
        mock_svc.add_security = AsyncMock(
            side_effect=WatchlistError(
                "max_securities_reached", "Maximum 100 securities per watchlist"
            )
        )

        app = _create_test_app(wl_svc=mock_svc)
        client = TestClient(app)
        resp = client.post("/api/v2/watchlists/wl-001/securities", json={"symbol": "HDFC"})

        assert resp.status_code == 400
        assert "100" in resp.json()["detail"]

    def test_add_missing_symbol_returns_422(self):
        mock_svc = AsyncMock(spec=WatchlistService)
        app = _create_test_app(wl_svc=mock_svc)
        client = TestClient(app)
        resp = client.post("/api/v2/watchlists/wl-001/securities", json={})
        assert resp.status_code == 422


# ── Remove Security Tests ────────────────────────────────────────────────────


class TestRemoveSecurity:
    def test_remove_success(self):
        mock_svc = AsyncMock(spec=WatchlistService)
        mock_svc.remove_security = AsyncMock(return_value=True)

        app = _create_test_app(wl_svc=mock_svc)
        client = TestClient(app)
        resp = client.delete("/api/v2/watchlists/wl-001/securities/TCS")

        assert resp.status_code == 200
        assert "removed" in resp.json()["message"].lower()

    def test_remove_not_in_watchlist_returns_400(self):
        mock_svc = AsyncMock(spec=WatchlistService)
        mock_svc.remove_security = AsyncMock(
            side_effect=WatchlistError(
                "security_not_in_watchlist", "Security 'XYZ' is not in this watchlist"
            )
        )

        app = _create_test_app(wl_svc=mock_svc)
        client = TestClient(app)
        resp = client.delete("/api/v2/watchlists/wl-001/securities/XYZ")

        assert resp.status_code == 400
        assert "not in" in resp.json()["detail"].lower()


# ── Prebuilt Watchlists Tests ────────────────────────────────────────────────


class TestPrebuiltWatchlists:
    def test_get_prebuilt(self):
        mock_svc = AsyncMock(spec=WatchlistService)
        mock_svc.get_prebuilt_watchlists = AsyncMock(
            return_value=[
                Watchlist(
                    id="pb-001", name="Nifty 50", is_prebuilt=True, sort_order=0, created_at=NOW
                ),
                Watchlist(
                    id="pb-002", name="Nifty Bank", is_prebuilt=True, sort_order=1, created_at=NOW
                ),
            ]
        )

        app = _create_test_app(wl_svc=mock_svc)
        client = TestClient(app)
        resp = client.get("/api/v2/watchlists/prebuilt")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert data["watchlists"][0]["name"] == "Nifty 50"
        assert data["watchlists"][0]["is_prebuilt"] is True

    def test_get_prebuilt_empty(self):
        mock_svc = AsyncMock(spec=WatchlistService)
        mock_svc.get_prebuilt_watchlists = AsyncMock(return_value=[])

        app = _create_test_app(wl_svc=mock_svc)
        client = TestClient(app)
        resp = client.get("/api/v2/watchlists/prebuilt")

        assert resp.status_code == 200
        assert resp.json()["count"] == 0


# ── RBAC Tests ───────────────────────────────────────────────────────────────


class TestWatchlistRBACEnforcement:
    def test_viewer_denied_create(self):
        mock_svc = AsyncMock(spec=WatchlistService)
        app = _create_test_app(wl_svc=mock_svc, role="VIEWER")
        client = TestClient(app)
        resp = client.post("/api/v2/watchlists", json={"name": "Test"})
        assert resp.status_code == 403

    def test_viewer_denied_delete(self):
        mock_svc = AsyncMock(spec=WatchlistService)
        app = _create_test_app(wl_svc=mock_svc, role="VIEWER")
        client = TestClient(app)
        resp = client.delete("/api/v2/watchlists/wl-001")
        assert resp.status_code == 403

    def test_viewer_denied_add_security(self):
        mock_svc = AsyncMock(spec=WatchlistService)
        app = _create_test_app(wl_svc=mock_svc, role="VIEWER")
        client = TestClient(app)
        resp = client.post("/api/v2/watchlists/wl-001/securities", json={"symbol": "TCS"})
        assert resp.status_code == 403

    def test_viewer_denied_remove_security(self):
        mock_svc = AsyncMock(spec=WatchlistService)
        app = _create_test_app(wl_svc=mock_svc, role="VIEWER")
        client = TestClient(app)
        resp = client.delete("/api/v2/watchlists/wl-001/securities/TCS")
        assert resp.status_code == 403

    def test_admin_allowed_list(self):
        mock_svc = AsyncMock(spec=WatchlistService)
        mock_svc.get_user_watchlists = AsyncMock(return_value=[])
        app = _create_test_app(wl_svc=mock_svc, role="ADMIN")
        client = TestClient(app)
        resp = client.get("/api/v2/watchlists")
        assert resp.status_code == 200

    def test_admin_allowed_prebuilt(self):
        mock_svc = AsyncMock(spec=WatchlistService)
        mock_svc.get_prebuilt_watchlists = AsyncMock(return_value=[])
        app = _create_test_app(wl_svc=mock_svc, role="ADMIN")
        client = TestClient(app)
        resp = client.get("/api/v2/watchlists/prebuilt")
        assert resp.status_code == 200
