"""Unit tests for market data API router endpoints."""

from datetime import date, datetime, timezone
from unittest.mock import MagicMock

from app.routers.auth_v2 import get_current_user_id, get_current_user_payload
from app.routers.market_data import (
    get_corporate_actions_collector,
    get_historical_data_service,
    get_market_data_collector,
    router,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ── Helpers ──────────────────────────────────────────────────────────────────

TEST_USER_ID = "test-user-market-001"


def _create_test_app(
    market_collector=None,
    corporate_collector=None,
    historical_service=None,
    role: str = "TRADER",
) -> FastAPI:
    """Create a minimal FastAPI app with the market_data router for testing."""
    app = FastAPI()
    app.include_router(router, prefix="/api/v2")

    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID
    app.dependency_overrides[get_current_user_payload] = lambda: {
        "sub": TEST_USER_ID,
        "email": "test@example.com",
        "role": role,
        "type": "access",
    }

    if market_collector is not None:
        app.dependency_overrides[get_market_data_collector] = lambda: market_collector
    if corporate_collector is not None:
        app.dependency_overrides[get_corporate_actions_collector] = lambda: corporate_collector
    if historical_service is not None:
        app.dependency_overrides[get_historical_data_service] = lambda: historical_service

    return app


# ── GET /market/price/{symbol} Tests ─────────────────────────────────────────


class TestGetPrice:
    def test_price_returns_data(self):
        mock_redis = MagicMock()
        mock_redis.hgetall.return_value = {
            "ltp": "2450.50",
            "last_traded_qty": "100",
            "volume": "5000000",
            "bid": "2450.00",
            "bid_qty": "200",
            "ask": "2451.00",
            "ask_qty": "150",
            "open": "2440.00",
            "high": "2460.00",
            "low": "2435.00",
            "close": "2445.00",
            "previous_close": "2442.00",
            "timestamp": "2024-01-15T10:30:00+05:30",
            "exchange": "NSE",
        }
        mock_event_bus = MagicMock()
        mock_event_bus.redis_client = mock_redis
        mock_collector = MagicMock()
        mock_collector.event_bus = mock_event_bus

        app = _create_test_app(market_collector=mock_collector)
        client = TestClient(app)
        resp = client.get("/api/v2/market/price/RELIANCE")

        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "RELIANCE"
        assert data["ltp"] == 2450.50
        assert data["volume"] == 5000000
        assert data["best_bid_price"] == 2450.00
        assert data["best_ask_price"] == 2451.00
        assert data["open"] == 2440.00
        assert data["high"] == 2460.00
        assert data["exchange"] == "NSE"

    def test_price_not_found(self):
        mock_redis = MagicMock()
        mock_redis.hgetall.return_value = {}
        mock_event_bus = MagicMock()
        mock_event_bus.redis_client = mock_redis
        mock_collector = MagicMock()
        mock_collector.event_bus = mock_event_bus

        app = _create_test_app(market_collector=mock_collector)
        client = TestClient(app)
        resp = client.get("/api/v2/market/price/NOSYMBOL")

        assert resp.status_code == 404
        assert "No price data" in resp.json()["detail"]

    def test_price_symbol_uppercased(self):
        mock_redis = MagicMock()
        mock_redis.hgetall.return_value = {
            "ltp": "100.0",
            "volume": "1000",
        }
        mock_event_bus = MagicMock()
        mock_event_bus.redis_client = mock_redis
        mock_collector = MagicMock()
        mock_collector.event_bus = mock_event_bus

        app = _create_test_app(market_collector=mock_collector)
        client = TestClient(app)
        resp = client.get("/api/v2/market/price/reliance")

        assert resp.status_code == 200
        assert resp.json()["symbol"] == "RELIANCE"
        # Verify Redis was queried with uppercased symbol
        mock_redis.hgetall.assert_called_with("price:RELIANCE")

    def test_price_service_not_initialized(self):
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
        resp = client.get("/api/v2/market/price/RELIANCE")
        assert resp.status_code == 503

    def test_price_redis_error_returns_500(self):
        mock_redis = MagicMock()
        mock_redis.hgetall.side_effect = Exception("Redis connection lost")
        mock_event_bus = MagicMock()
        mock_event_bus.redis_client = mock_redis
        mock_collector = MagicMock()
        mock_collector.event_bus = mock_event_bus

        app = _create_test_app(market_collector=mock_collector)
        client = TestClient(app)
        resp = client.get("/api/v2/market/price/RELIANCE")

        assert resp.status_code == 500


# ── GET /market/depth/{symbol} Tests ─────────────────────────────────────────


class TestGetDepth:
    def _make_mock_collector_with_depth(self, depth_data):
        mock_collector = MagicMock()
        mock_collector.get_order_book_depth.return_value = depth_data
        return mock_collector

    def test_depth_returns_data(self):
        from src.ingestion.market_data_collector import OrderBookDepth, OrderBookLevel

        depth = OrderBookDepth(
            symbol="INFY",
            bids=[
                OrderBookLevel(price=1500.00, quantity=100),
                OrderBookLevel(price=1499.50, quantity=200),
            ],
            asks=[
                OrderBookLevel(price=1500.50, quantity=150),
                OrderBookLevel(price=1501.00, quantity=250),
            ],
            timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
        )
        mock_collector = self._make_mock_collector_with_depth(depth)

        app = _create_test_app(market_collector=mock_collector)
        client = TestClient(app)
        resp = client.get("/api/v2/market/depth/INFY")

        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "INFY"
        assert len(data["bids"]) == 2
        assert len(data["asks"]) == 2
        assert data["bids"][0]["price"] == 1500.00
        assert data["bids"][0]["quantity"] == 100
        assert data["asks"][0]["price"] == 1500.50
        assert data["timestamp"] is not None

    def test_depth_not_found(self):
        mock_collector = self._make_mock_collector_with_depth(None)

        app = _create_test_app(market_collector=mock_collector)
        client = TestClient(app)
        resp = client.get("/api/v2/market/depth/NOSYMBOL")

        assert resp.status_code == 404
        assert "No order book depth" in resp.json()["detail"]

    def test_depth_symbol_uppercased(self):
        mock_collector = MagicMock()
        mock_collector.get_order_book_depth.return_value = None

        app = _create_test_app(market_collector=mock_collector)
        client = TestClient(app)
        resp = client.get("/api/v2/market/depth/infy")

        # Verify the collector was called with uppercased symbol
        mock_collector.get_order_book_depth.assert_called_with("INFY")

    def test_depth_empty_bids_asks(self):
        from src.ingestion.market_data_collector import OrderBookDepth

        depth = OrderBookDepth(symbol="TCS", bids=[], asks=[], timestamp=None)
        mock_collector = self._make_mock_collector_with_depth(depth)

        app = _create_test_app(market_collector=mock_collector)
        client = TestClient(app)
        resp = client.get("/api/v2/market/depth/TCS")

        assert resp.status_code == 200
        data = resp.json()
        assert data["bids"] == []
        assert data["asks"] == []
        assert data["timestamp"] is None

    def test_depth_service_not_initialized(self):
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
        resp = client.get("/api/v2/market/depth/INFY")
        assert resp.status_code == 503


# ── GET /market/corporate-actions Tests ──────────────────────────────────────


class TestGetCorporateActions:
    def _make_mock_collector(self, actions=None):
        mock_collector = MagicMock()
        mock_collector.get_action_history.return_value = actions or []
        return mock_collector

    def test_corporate_actions_returns_list(self):
        from src.ingestion.corporate_actions_collector import (
            CorporateAction,
            CorporateActionType,
        )

        actions = [
            CorporateAction(
                symbol="RELIANCE",
                action_type=CorporateActionType.DIVIDEND,
                ex_date=date(2024, 1, 15),
                record_date=date(2024, 1, 17),
                details={"amount": "10.00", "currency": "INR"},
                source="NSE",
                fetched_at=datetime(2024, 1, 10, 12, 0, 0, tzinfo=timezone.utc),
            ),
            CorporateAction(
                symbol="TCS",
                action_type=CorporateActionType.SPLIT,
                ex_date=date(2024, 2, 1),
                details={"ratio": "5:1"},
                source="BSE",
            ),
        ]
        mock_collector = self._make_mock_collector(actions)

        app = _create_test_app(corporate_collector=mock_collector)
        client = TestClient(app)
        resp = client.get("/api/v2/market/corporate-actions")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert data["actions"][0]["symbol"] == "RELIANCE"
        assert data["actions"][0]["action_type"] == "DIVIDEND"
        assert data["actions"][0]["ex_date"] == "2024-01-15"
        assert data["actions"][1]["symbol"] == "TCS"
        assert data["actions"][1]["action_type"] == "SPLIT"

    def test_corporate_actions_filter_by_symbol(self):
        from src.ingestion.corporate_actions_collector import (
            CorporateAction,
            CorporateActionType,
        )

        actions = [
            CorporateAction(
                symbol="RELIANCE",
                action_type=CorporateActionType.BONUS,
                ex_date=date(2024, 3, 1),
                details={"ratio": "1:1"},
            ),
        ]
        mock_collector = self._make_mock_collector(actions)

        app = _create_test_app(corporate_collector=mock_collector)
        client = TestClient(app)
        resp = client.get("/api/v2/market/corporate-actions?symbol=RELIANCE")

        assert resp.status_code == 200
        # Verify the collector was called with the symbol filter
        mock_collector.get_action_history.assert_called_once_with(
            symbol="RELIANCE",
            action_type=None,
        )

    def test_corporate_actions_filter_by_action_type(self):
        mock_collector = self._make_mock_collector([])

        app = _create_test_app(corporate_collector=mock_collector)
        client = TestClient(app)
        resp = client.get("/api/v2/market/corporate-actions?action_type=DIVIDEND")

        assert resp.status_code == 200
        call_args = mock_collector.get_action_history.call_args
        from src.ingestion.corporate_actions_collector import CorporateActionType

        assert call_args.kwargs["action_type"] == CorporateActionType.DIVIDEND

    def test_corporate_actions_invalid_action_type(self):
        mock_collector = self._make_mock_collector([])

        app = _create_test_app(corporate_collector=mock_collector)
        client = TestClient(app)
        resp = client.get("/api/v2/market/corporate-actions?action_type=INVALID")

        assert resp.status_code == 400
        assert "Invalid action_type" in resp.json()["detail"]

    def test_corporate_actions_empty(self):
        mock_collector = self._make_mock_collector([])

        app = _create_test_app(corporate_collector=mock_collector)
        client = TestClient(app)
        resp = client.get("/api/v2/market/corporate-actions")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["actions"] == []

    def test_corporate_actions_service_not_initialized(self):
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
        resp = client.get("/api/v2/market/corporate-actions")
        assert resp.status_code == 503


# ── GET /market/historical/{symbol} Tests ────────────────────────────────────


class TestGetHistorical:
    def _make_mock_service(self, bars=None):
        mock_service = MagicMock()
        mock_service.query.return_value = bars or []
        return mock_service

    def test_historical_returns_daily_data(self):
        from src.ingestion.historical_data_service import OHLCV

        bars = [
            OHLCV(
                symbol="INFY",
                date=date(2024, 1, 2),
                open=1500,
                high=1520,
                low=1490,
                close=1510,
                volume=3000000,
            ),
            OHLCV(
                symbol="INFY",
                date=date(2024, 1, 3),
                open=1510,
                high=1530,
                low=1505,
                close=1525,
                volume=2800000,
            ),
        ]
        mock_service = self._make_mock_service(bars)

        app = _create_test_app(historical_service=mock_service)
        client = TestClient(app)
        resp = client.get(
            "/api/v2/market/historical/INFY?start_date=2024-01-01&end_date=2024-01-31"
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "INFY"
        assert data["timeframe"] == "daily"
        assert data["count"] == 2
        assert data["bars"][0]["date"] == "2024-01-02"
        assert data["bars"][0]["close"] == 1510
        assert data["bars"][1]["volume"] == 2800000

    def test_historical_weekly_timeframe(self):
        mock_service = self._make_mock_service([])

        app = _create_test_app(historical_service=mock_service)
        client = TestClient(app)
        resp = client.get(
            "/api/v2/market/historical/TCS?start_date=2024-01-01&end_date=2024-03-31&timeframe=weekly"
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["timeframe"] == "weekly"
        # Verify the service was called with the correct timeframe
        from src.ingestion.historical_data_service import Timeframe

        call_args = mock_service.query.call_args
        assert call_args.kwargs["timeframe"] == Timeframe.WEEKLY

    def test_historical_monthly_timeframe(self):
        mock_service = self._make_mock_service([])

        app = _create_test_app(historical_service=mock_service)
        client = TestClient(app)
        resp = client.get(
            "/api/v2/market/historical/TCS?start_date=2024-01-01&end_date=2024-12-31&timeframe=monthly"
        )

        assert resp.status_code == 200
        assert resp.json()["timeframe"] == "monthly"

    def test_historical_invalid_timeframe(self):
        mock_service = self._make_mock_service([])

        app = _create_test_app(historical_service=mock_service)
        client = TestClient(app)
        resp = client.get(
            "/api/v2/market/historical/TCS?start_date=2024-01-01&end_date=2024-01-31&timeframe=hourly"
        )

        assert resp.status_code == 400
        assert "Invalid timeframe" in resp.json()["detail"]

    def test_historical_invalid_start_date(self):
        mock_service = self._make_mock_service([])

        app = _create_test_app(historical_service=mock_service)
        client = TestClient(app)
        resp = client.get("/api/v2/market/historical/TCS?start_date=not-a-date&end_date=2024-01-31")

        assert resp.status_code == 400
        assert "Invalid start_date" in resp.json()["detail"]

    def test_historical_invalid_end_date(self):
        mock_service = self._make_mock_service([])

        app = _create_test_app(historical_service=mock_service)
        client = TestClient(app)
        resp = client.get("/api/v2/market/historical/TCS?start_date=2024-01-01&end_date=bad")

        assert resp.status_code == 400
        assert "Invalid end_date" in resp.json()["detail"]

    def test_historical_start_after_end(self):
        mock_service = self._make_mock_service([])

        app = _create_test_app(historical_service=mock_service)
        client = TestClient(app)
        resp = client.get("/api/v2/market/historical/TCS?start_date=2024-06-01&end_date=2024-01-01")

        assert resp.status_code == 400
        assert "start_date must be before" in resp.json()["detail"]

    def test_historical_missing_dates(self):
        mock_service = self._make_mock_service([])

        app = _create_test_app(historical_service=mock_service)
        client = TestClient(app)
        resp = client.get("/api/v2/market/historical/TCS")

        assert resp.status_code == 422  # FastAPI validation error for missing required query params

    def test_historical_empty_result(self):
        mock_service = self._make_mock_service([])

        app = _create_test_app(historical_service=mock_service)
        client = TestClient(app)
        resp = client.get(
            "/api/v2/market/historical/UNKNOWN?start_date=2024-01-01&end_date=2024-01-31"
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["bars"] == []

    def test_historical_symbol_uppercased(self):
        mock_service = self._make_mock_service([])

        app = _create_test_app(historical_service=mock_service)
        client = TestClient(app)
        resp = client.get(
            "/api/v2/market/historical/infy?start_date=2024-01-01&end_date=2024-01-31"
        )

        assert resp.status_code == 200
        assert resp.json()["symbol"] == "INFY"
        call_args = mock_service.query.call_args
        assert call_args.kwargs["symbol"] == "INFY"

    def test_historical_service_not_initialized(self):
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
        resp = client.get(
            "/api/v2/market/historical/INFY?start_date=2024-01-01&end_date=2024-01-31"
        )
        assert resp.status_code == 503


# ── RBAC Tests ───────────────────────────────────────────────────────────────


class TestMarketDataRBAC:
    def _make_mocks(self):
        mock_redis = MagicMock()
        mock_redis.hgetall.return_value = {"ltp": "100.0"}
        mock_event_bus = MagicMock()
        mock_event_bus.redis_client = mock_redis
        mock_collector = MagicMock()
        mock_collector.event_bus = mock_event_bus
        mock_collector.get_order_book_depth.return_value = None
        mock_corp = MagicMock()
        mock_corp.get_action_history.return_value = []
        mock_hist = MagicMock()
        mock_hist.query.return_value = []
        return mock_collector, mock_corp, mock_hist

    def test_viewer_denied_price(self):
        mc, cc, hs = self._make_mocks()
        app = _create_test_app(
            market_collector=mc, corporate_collector=cc, historical_service=hs, role="VIEWER"
        )
        client = TestClient(app)
        resp = client.get("/api/v2/market/price/RELIANCE")
        assert resp.status_code == 403

    def test_viewer_denied_depth(self):
        mc, cc, hs = self._make_mocks()
        app = _create_test_app(
            market_collector=mc, corporate_collector=cc, historical_service=hs, role="VIEWER"
        )
        client = TestClient(app)
        resp = client.get("/api/v2/market/depth/RELIANCE")
        assert resp.status_code == 403

    def test_viewer_denied_corporate_actions(self):
        mc, cc, hs = self._make_mocks()
        app = _create_test_app(
            market_collector=mc, corporate_collector=cc, historical_service=hs, role="VIEWER"
        )
        client = TestClient(app)
        resp = client.get("/api/v2/market/corporate-actions")
        assert resp.status_code == 403

    def test_viewer_denied_historical(self):
        mc, cc, hs = self._make_mocks()
        app = _create_test_app(
            market_collector=mc, corporate_collector=cc, historical_service=hs, role="VIEWER"
        )
        client = TestClient(app)
        resp = client.get(
            "/api/v2/market/historical/INFY?start_date=2024-01-01&end_date=2024-01-31"
        )
        assert resp.status_code == 403

    def test_admin_allowed_price(self):
        mc, cc, hs = self._make_mocks()
        app = _create_test_app(market_collector=mc, role="ADMIN")
        client = TestClient(app)
        resp = client.get("/api/v2/market/price/RELIANCE")
        assert resp.status_code == 200

    def test_admin_allowed_corporate_actions(self):
        mc, cc, hs = self._make_mocks()
        app = _create_test_app(corporate_collector=cc, role="ADMIN")
        client = TestClient(app)
        resp = client.get("/api/v2/market/corporate-actions")
        assert resp.status_code == 200

    def test_admin_allowed_historical(self):
        mc, cc, hs = self._make_mocks()
        app = _create_test_app(historical_service=hs, role="ADMIN")
        client = TestClient(app)
        resp = client.get(
            "/api/v2/market/historical/INFY?start_date=2024-01-01&end_date=2024-01-31"
        )
        assert resp.status_code == 200
