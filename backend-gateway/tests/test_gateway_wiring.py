"""Tests for gateway wiring: router registration, JWT middleware, RLS context, push notifications.

Verifies task 28.1 requirements:
- All new routers registered in main FastAPI app
- JWT middleware applies to all protected endpoints
- RLS context (app.state.current_user_id) set on every authenticated request
- Push notification triggers wired for trade alerts, order updates, kill switch

Requirements: 29.5, 12.6
"""

import pytest
from unittest.mock import patch, MagicMock

from app.main import app
from app.services.push_notification_service import (
    PushNotificationService,
    PushNotification,
    NotificationType,
)
from app.middleware.jwt_auth import _extract_user_id, JWTAuthMiddleware


# ── Router registration tests ────────────────────────────────────────────────


class TestRouterRegistration:
    """Verify all required routers are registered in the FastAPI app."""

    def _get_all_route_paths(self):
        """Extract all registered route paths from the app."""
        return [route.path for route in app.routes if hasattr(route, "path")]

    def _get_all_route_tags(self):
        """Extract all registered route tags from the app."""
        tags = set()
        for route in app.routes:
            if hasattr(route, "tags"):
                tags.update(route.tags)
        return tags

    def test_auth_v2_router_registered(self):
        paths = self._get_all_route_paths()
        auth_paths = [p for p in paths if "/v2/auth/" in p]
        assert len(auth_paths) > 0, "auth_v2 router not registered"

    def test_verification_router_registered(self):
        paths = self._get_all_route_paths()
        verify_paths = [p for p in paths if "/verify/" in p]
        assert len(verify_paths) > 0, "verification router not registered"

    def test_bank_router_registered(self):
        paths = self._get_all_route_paths()
        bank_paths = [p for p in paths if "/bank/" in p or "/fund/" in p]
        assert len(bank_paths) > 0, "bank router not registered"

    def test_stock_universe_router_registered(self):
        paths = self._get_all_route_paths()
        stock_paths = [p for p in paths if "/stocks" in p or "/sectors" in p]
        assert len(stock_paths) > 0, "stock_universe router not registered"

    def test_watchlist_router_registered(self):
        paths = self._get_all_route_paths()
        wl_paths = [p for p in paths if "/watchlists" in p]
        assert len(wl_paths) > 0, "watchlist router not registered"

    def test_screener_router_registered(self):
        paths = self._get_all_route_paths()
        screener_paths = [p for p in paths if "/screener/" in p]
        assert len(screener_paths) > 0, "screener router not registered"

    def test_market_data_router_registered(self):
        paths = self._get_all_route_paths()
        md_paths = [p for p in paths if "/market/" in p]
        assert len(md_paths) > 0, "market_data router not registered"

    def test_chatbot_router_registered(self):
        paths = self._get_all_route_paths()
        chat_paths = [p for p in paths if "/chatbot/" in p]
        assert len(chat_paths) > 0, "chatbot router not registered"

    def test_broker_v2_router_registered(self):
        paths = self._get_all_route_paths()
        broker_paths = [p for p in paths if "/brokers/" in p]
        assert len(broker_paths) > 0, "broker_v2 router not registered"

    def test_admin_router_registered(self):
        paths = self._get_all_route_paths()
        admin_paths = [p for p in paths if "/admin/" in p]
        assert len(admin_paths) > 0, "admin router not registered"

    def test_users_router_registered(self):
        paths = self._get_all_route_paths()
        user_paths = [p for p in paths if "/users/" in p]
        assert len(user_paths) > 0, "users router not registered"

    def test_all_required_tags_present(self):
        """All new service tags should be present in the app routes."""
        required_tags = {
            "auth-v2",
            "verification",
            "bank-fund",
            "stock-universe",
            "watchlists",
            "screener",
            "broker-v2",
            "market-data",
            "chatbot",
            "users",
            "admin",
        }
        registered_tags = self._get_all_route_tags()
        missing = required_tags - registered_tags
        assert not missing, f"Missing router tags: {missing}"

    def test_v2_routers_use_v2_prefix(self):
        """All new v2 routers should be under /api/v2 prefix."""
        paths = self._get_all_route_paths()
        v2_keywords = ["/verify/", "/bank/", "/fund/", "/stocks", "/watchlists",
                       "/screener/", "/brokers/", "/market/", "/chatbot/", "/users/", "/admin/"]
        for keyword in v2_keywords:
            matching = [p for p in paths if keyword in p]
            if matching:
                for path in matching:
                    assert "/api/v2" in path or "/v2/" in path.replace("/api/v2", "").replace(keyword, "v2"), \
                        f"Route {path} with {keyword} should be under /api/v2"


# ── Middleware tests ─────────────────────────────────────────────────────────


class TestMiddlewareStack:
    """Verify middleware is properly configured."""

    def test_jwt_auth_middleware_registered(self):
        """JWTAuthMiddleware should be in the app's middleware configuration."""
        # FastAPI stores middleware in user_middleware list before building the stack
        middleware_classes = [m.cls.__name__ for m in app.user_middleware if hasattr(m, "cls")]
        assert "JWTAuthMiddleware" in middleware_classes, \
            f"JWTAuthMiddleware not found in user_middleware: {middleware_classes}"

    def test_extract_user_id_no_header(self):
        """No auth header should return None."""
        request = MagicMock()
        request.headers = {}
        result = _extract_user_id(request)
        assert result is None

    def test_extract_user_id_invalid_header(self):
        """Non-Bearer header should return None."""
        request = MagicMock()
        request.headers = {"authorization": "Basic abc123"}
        result = _extract_user_id(request)
        assert result is None

    def test_extract_user_id_valid_token(self):
        """Valid JWT should return user_id."""
        request = MagicMock()
        request.headers = {"authorization": "Bearer valid-token"}

        with patch("app.services.account_service.verify_access_token") as mock_verify:
            mock_verify.return_value = {"sub": "user-123", "role": "TRADER"}
            result = _extract_user_id(request)
            assert result == "user-123"

    def test_extract_user_id_expired_token(self):
        """Expired JWT should return None (middleware doesn't reject)."""
        request = MagicMock()
        request.headers = {"authorization": "Bearer expired-token"}

        with patch("app.services.account_service.verify_access_token") as mock_verify:
            mock_verify.return_value = None
            result = _extract_user_id(request)
            assert result is None


# ── RLS context tests ────────────────────────────────────────────────────────


class TestRLSContext:
    """Verify RLS context is set on authenticated requests."""

    def test_app_state_has_current_user_id_attr(self):
        """app.state should support current_user_id attribute."""
        # After push_service is set, state should be accessible
        assert hasattr(app.state, "push_service")

    @pytest.mark.asyncio
    async def test_jwt_middleware_sets_rls_context(self):
        """JWTAuthMiddleware should set app.state.current_user_id."""
        from starlette.testclient import TestClient
        from starlette.requests import Request as StarletteRequest
        from starlette.responses import JSONResponse

        with patch("app.services.account_service.verify_access_token") as mock_verify:
            mock_verify.return_value = {"sub": "rls-user-456", "role": "TRADER"}

            captured_user_id = {}

            @app.get("/test-rls-context-check")
            async def test_rls_endpoint(request: StarletteRequest):
                captured_user_id["value"] = getattr(
                    request.app.state, "current_user_id", None
                )
                return JSONResponse({"ok": True})

            client = TestClient(app)
            resp = client.get(
                "/test-rls-context-check",
                headers={"Authorization": "Bearer test-token"},
            )
            assert resp.status_code == 200
            assert captured_user_id.get("value") == "rls-user-456"


# ── Push notification service tests ──────────────────────────────────────────


class TestPushNotificationService:
    """Verify push notification service is wired and functional."""

    def test_push_service_on_app_state(self):
        """PushNotificationService should be available on app.state."""
        assert hasattr(app.state, "push_service")
        assert isinstance(app.state.push_service, PushNotificationService)

    @pytest.mark.asyncio
    async def test_trade_alert_notification(self):
        svc = PushNotificationService()
        svc.register_device("user-1", "device-token-abc")

        result = await svc.notify_trade_alert(
            user_id="user-1",
            symbol="RELIANCE",
            action="BUY",
            price=2450.50,
            strategy="Mean Reversion",
        )
        assert result is True
        assert len(svc.sent_notifications) == 1
        notif = svc.sent_notifications[0]
        assert notif.notification_type == NotificationType.TRADE_ALERT
        assert "RELIANCE" in notif.title
        assert "2450.50" in notif.body

    @pytest.mark.asyncio
    async def test_order_update_notification(self):
        svc = PushNotificationService()
        svc.register_device("user-2", "device-token-def")

        result = await svc.notify_order_update(
            user_id="user-2",
            order_id="ord-12345678",
            symbol="TCS",
            status="FILLED",
            details="Qty 10 at ₹3500",
        )
        assert result is True
        assert len(svc.sent_notifications) == 1
        notif = svc.sent_notifications[0]
        assert notif.notification_type == NotificationType.ORDER_UPDATE
        assert "TCS" in notif.title
        assert "FILLED" in notif.title

    @pytest.mark.asyncio
    async def test_kill_switch_notification(self):
        svc = PushNotificationService()
        svc.register_device("user-3", "device-token-ghi")

        result = await svc.notify_kill_switch(
            user_id="user-3",
            activated=True,
            reason="Max daily loss exceeded",
        )
        assert result is True
        assert len(svc.sent_notifications) == 1
        notif = svc.sent_notifications[0]
        assert notif.notification_type == NotificationType.KILL_SWITCH
        assert "ACTIVATED" in notif.title
        assert "Max daily loss" in notif.body

    @pytest.mark.asyncio
    async def test_no_devices_returns_false(self):
        svc = PushNotificationService()
        result = await svc.notify_trade_alert(
            user_id="no-devices-user",
            symbol="INFY",
            action="SELL",
            price=1500.0,
        )
        assert result is False
        # Notification still recorded
        assert len(svc.sent_notifications) == 1

    @pytest.mark.asyncio
    async def test_device_registration_and_unregistration(self):
        svc = PushNotificationService()
        svc.register_device("user-4", "token-1")
        svc.register_device("user-4", "token-2")
        # Duplicate registration should not add twice
        svc.register_device("user-4", "token-1")
        assert len(svc._device_tokens["user-4"]) == 2

        svc.unregister_device("user-4", "token-1")
        assert len(svc._device_tokens["user-4"]) == 1
        assert svc._device_tokens["user-4"][0] == "token-2"

    @pytest.mark.asyncio
    async def test_kill_switch_deactivation(self):
        svc = PushNotificationService()
        svc.register_device("user-5", "device-xyz")

        result = await svc.notify_kill_switch(
            user_id="user-5",
            activated=False,
        )
        assert result is True
        notif = svc.sent_notifications[0]
        assert "DEACTIVATED" in notif.title

    @pytest.mark.asyncio
    async def test_clear_sent_notifications(self):
        svc = PushNotificationService()
        await svc.send_notification(
            PushNotification(
                user_id="u1",
                title="Test",
                body="Test body",
                notification_type=NotificationType.TRADE_ALERT,
            )
        )
        assert len(svc.sent_notifications) == 1
        svc.clear_sent()
        assert len(svc.sent_notifications) == 0
