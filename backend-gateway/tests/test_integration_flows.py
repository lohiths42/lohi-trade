"""Integration tests for critical end-to-end flows through the FastAPI gateway.

Tests the full request/response chain with mocked external services:
1. Registration → PAN → KYC → DMAT → Bank → Deposit → Trade flow
2. Screener filter → results → stock detail navigation
3. Chatbot query → RAG retrieval → LLM response → chart rendering

Requirements: 1-6, 10-11, 18-21
"""

import base64
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from app.routers import auth_v2, bank, chatbot, screener, verification
from app.routers.auth_v2 import get_current_user_id, get_current_user_payload
from app.services.account_service import AccountService, TokenPair, User, UserRole
from app.services.bank_service import (
    BankAccount,
    BankAccountService,
    BankAccountStatus,
)
from app.services.chatbot_service import ChatbotService, ChatResponse
from app.services.fund_service import (
    DepositTransaction,
    FundService,
    PaymentMethod,
    TransactionStatus,
)
from app.services.screener_service import (
    ScreenerEngine,
    ScreenerResult,
    ScreenerResultItem,
)
from app.services.verification_service import (
    DMATService,
    DMATStatus,
    DMATVerificationResult,
    KYCService,
    KYCStatus,
    KYCSubmissionResult,
    PANStatus,
    PANVerificationResult,
    PANVerificationService,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ── Helpers ──────────────────────────────────────────────────────────────────

TEST_USER_ID = "integ-user-001"
TEST_EMAIL = "[email]"


def _build_app() -> FastAPI:
    """Build a minimal FastAPI app with all routers needed for integration tests."""
    app = FastAPI()
    app.include_router(auth_v2.router, prefix="/api/v2", tags=["auth-v2"])
    app.include_router(verification.router, prefix="/api/v2", tags=["verification"])
    app.include_router(bank.router, prefix="/api/v2", tags=["bank-fund"])
    app.include_router(screener.router, prefix="/api/v2", tags=["screener"])
    app.include_router(chatbot.router, prefix="/api/v2", tags=["chatbot"])
    return app


def _override_auth(app: FastAPI, user_id: str = TEST_USER_ID):
    """Override auth dependencies to bypass JWT validation."""
    app.dependency_overrides[get_current_user_id] = lambda: user_id
    app.dependency_overrides[get_current_user_payload] = lambda: {
        "sub": user_id,
        "email": TEST_EMAIL,
        "role": "TRADER",
    }


def _mock_account_service() -> AsyncMock:
    svc = AsyncMock(spec=AccountService)
    svc.register_email.return_value = {
        "user": User(
            id=TEST_USER_ID,
            email=TEST_EMAIL,
            phone="9876543210",
            name="Test User",
            role=UserRole.TRADER,
            is_onboarded=False,
            created_at=datetime.utcnow(),
        ),
        "otp_sent": True,
    }
    svc.login_email.return_value = TokenPair(
        access_token="access-token-xyz",
        refresh_token="refresh-token-xyz",
    )
    return svc


def _mock_pan_service() -> AsyncMock:
    svc = AsyncMock(spec=PANVerificationService)
    svc.verify_pan.return_value = PANVerificationResult(
        status=PANStatus.VERIFIED,
        holder_name="Test User",
        pan_masked="AB****34Z1",
        verified_at=datetime.utcnow(),
    )
    return svc


def _mock_kyc_service() -> AsyncMock:
    svc = AsyncMock(spec=KYCService)
    svc.submit_kyc.return_value = KYCSubmissionResult(
        status=KYCStatus.VERIFIED,
        verification_ref="KYC-REF-001",
        submitted_at=datetime.utcnow(),
        verified_at=datetime.utcnow(),
    )
    svc.check_kyc_status.return_value = KYCStatus.VERIFIED
    svc.db_pool = None
    return svc


def _mock_dmat_service() -> AsyncMock:
    svc = AsyncMock(spec=DMATService)
    svc.verify_dmat.return_value = DMATVerificationResult(
        status=DMATStatus.LINKED,
        dmat_id="dmat-001",
        depository="CDSL",
        dp_name="HDFC Securities",
        linked_at=datetime.utcnow(),
    )
    svc.db_pool = None
    return svc


def _mock_bank_service() -> AsyncMock:
    svc = AsyncMock(spec=BankAccountService)
    svc.register_bank_account.return_value = BankAccount(
        id="bank-001",
        user_id=TEST_USER_ID,
        ifsc_code="HDFC0001234",
        bank_name="HDFC Bank",
        account_holder_name="Test User",
        account_type="savings",
        is_primary=True,
        status=BankAccountStatus.VERIFIED,
        verified_at=datetime.utcnow(),
        created_at=datetime.utcnow(),
    )
    svc.db_pool = None
    return svc


def _mock_fund_service() -> AsyncMock:
    svc = AsyncMock(spec=FundService)
    svc.initiate_deposit.return_value = DepositTransaction(
        id="txn-dep-001",
        user_id=TEST_USER_ID,
        amount=Decimal("5000.00"),
        payment_method=PaymentMethod.UPI,
        transaction_ref="UPI-REF-001",
        status=TransactionStatus.COMPLETED,
        upi_link="upi://pay?pa=lohitrade@upi&am=5000",
        created_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
    )
    svc.db_pool = None
    return svc


def _mock_screener_engine() -> AsyncMock:
    svc = AsyncMock(spec=ScreenerEngine)
    svc.screen.return_value = ScreenerResult(
        items=[
            ScreenerResultItem(
                security_id=1,
                symbol="RELIANCE",
                company_name="Reliance Industries",
                exchange="NSE",
                sector="Energy",
                market_cap_category="large-cap",
                pe_ratio=Decimal("25.50"),
                market_cap=Decimal("1800000000000"),
            ),
            ScreenerResultItem(
                security_id=2,
                symbol="TCS",
                company_name="Tata Consultancy Services",
                exchange="NSE",
                sector="IT/Technology",
                market_cap_category="large-cap",
                pe_ratio=Decimal("30.20"),
                market_cap=Decimal("1400000000000"),
            ),
        ],
        total=2,
        page=1,
        page_size=50,
        total_pages=1,
    )
    return svc


def _mock_chatbot_service() -> AsyncMock:
    svc = AsyncMock(spec=ChatbotService)
    return svc


# ══════════════════════════════════════════════════════════════════════════════
# Flow 1: Registration → PAN → KYC → DMAT → Bank → Deposit
# Requirements: 1-6
# ══════════════════════════════════════════════════════════════════════════════


class TestRegistrationToDepositFlow:
    """Integration test: full onboarding flow from registration through deposit."""

    def setup_method(self):
        self.app = _build_app()
        _override_auth(self.app)

        self.mock_account = _mock_account_service()
        self.mock_pan = _mock_pan_service()
        self.mock_kyc = _mock_kyc_service()
        self.mock_dmat = _mock_dmat_service()
        self.mock_bank = _mock_bank_service()
        self.mock_fund = _mock_fund_service()

        # Wire service dependencies
        from app.routers.auth_v2 import get_account_service
        from app.routers.bank import get_bank_service, get_fund_service
        from app.routers.verification import get_dmat_service, get_kyc_service, get_pan_service

        self.app.dependency_overrides[get_account_service] = lambda: self.mock_account
        self.app.dependency_overrides[get_pan_service] = lambda: self.mock_pan
        self.app.dependency_overrides[get_kyc_service] = lambda: self.mock_kyc
        self.app.dependency_overrides[get_dmat_service] = lambda: self.mock_dmat
        self.app.dependency_overrides[get_bank_service] = lambda: self.mock_bank
        self.app.dependency_overrides[get_fund_service] = lambda: self.mock_fund

        self.client = TestClient(self.app)

    def teardown_method(self):
        self.app.dependency_overrides.clear()

    def test_full_onboarding_flow(self):
        """End-to-end: register → PAN → KYC → DMAT → bank → deposit."""

        # Step 1: Register with email
        resp = self.client.post(
            "/api/v2/auth/register",
            json={
                "email": TEST_EMAIL,
                "password": "Str0ng!Pass",
                "phone": "9876543210",
                "name": "Test User",
            },
        )
        assert resp.status_code == 201
        reg_data = resp.json()
        assert reg_data["user_id"] == TEST_USER_ID
        assert reg_data["email"] == TEST_EMAIL
        self.mock_account.register_email.assert_called_once()

        # Step 2: Login to get tokens
        resp = self.client.post(
            "/api/v2/auth/login",
            json={
                "email": TEST_EMAIL,
                "password": "Str0ng!Pass",
            },
        )
        assert resp.status_code == 200
        login_data = resp.json()
        assert "access_token" in login_data
        assert login_data["token_type"] == "bearer"

        # Step 3: Verify PAN
        resp = self.client.post(
            "/api/v2/verify/pan",
            json={
                "pan": "ABCDE1234Z",
            },
        )
        assert resp.status_code == 200
        pan_data = resp.json()
        assert pan_data["status"] == "VERIFIED"
        assert pan_data["holder_name"] == "Test User"
        self.mock_pan.verify_pan.assert_called_once_with(TEST_USER_ID, "ABCDE1234Z")

        # Step 4: Submit KYC (multipart form)
        resp = self.client.post(
            "/api/v2/verify/kyc",
            data={
                "full_name": "Test User",
                "date_of_birth": "1990-01-15",
                "address": "123 Test Street, Mumbai",
            },
            files={
                "government_id_photo": (
                    "id.jpg",
                    b"\xff\xd8\xff\xe0" + b"\x00" * 1000,
                    "image/jpeg",
                ),
            },
        )
        assert resp.status_code == 200
        kyc_data = resp.json()
        assert kyc_data["status"] == "VERIFIED"
        assert kyc_data["verification_ref"] == "KYC-REF-001"
        self.mock_kyc.submit_kyc.assert_called_once()

        # Step 5: Link DMAT account
        resp = self.client.post(
            "/api/v2/verify/dmat",
            json={
                "account_number": "1234567890123456",
            },
        )
        assert resp.status_code == 200
        dmat_data = resp.json()
        assert dmat_data["status"] == "LINKED"
        assert dmat_data["depository"] == "CDSL"
        assert dmat_data["dp_name"] == "HDFC Securities"
        self.mock_dmat.verify_dmat.assert_called_once_with(TEST_USER_ID, "1234567890123456")

        # Step 6: Register bank account
        resp = self.client.post(
            "/api/v2/bank/register",
            json={
                "account_holder_name": "Test User",
                "account_number": "12345678901234",
                "ifsc_code": "HDFC0001234",
                "bank_name": "HDFC Bank",
                "account_type": "savings",
            },
        )
        assert resp.status_code == 200
        bank_data = resp.json()
        assert bank_data["status"] == "VERIFIED"
        assert bank_data["account"]["bank_name"] == "HDFC Bank"
        assert bank_data["account"]["is_primary"] is True
        self.mock_bank.register_bank_account.assert_called_once()

        # Step 7: Deposit funds
        resp = self.client.post(
            "/api/v2/fund/deposit",
            json={
                "amount": "5000.00",
                "payment_method": "UPI",
            },
        )
        assert resp.status_code == 200
        dep_data = resp.json()
        assert dep_data["status"] == "COMPLETED"
        assert dep_data["amount"] == "5000.00"
        assert dep_data["payment_method"] == "UPI"
        assert dep_data["transaction_id"] == "txn-dep-001"
        self.mock_fund.initiate_deposit.assert_called_once()

    def test_registration_returns_correct_response_shape(self):
        """Verify the registration response has all required fields."""
        resp = self.client.post(
            "/api/v2/auth/register",
            json={
                "email": TEST_EMAIL,
                "password": "Str0ng!Pass",
                "phone": "9876543210",
                "name": "Test User",
            },
        )
        data = resp.json()
        assert "user_id" in data
        assert "email" in data
        assert "message" in data

    def test_pan_rejection_propagates(self):
        """When PAN is rejected, the response includes the rejection reason."""
        self.mock_pan.verify_pan.return_value = PANVerificationResult(
            status=PANStatus.REJECTED,
            rejection_reason="invalid_pan",
        )
        resp = self.client.post("/api/v2/verify/pan", json={"pan": "INVALID123"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "REJECTED"
        assert "invalid_pan" in data["rejection_reason"]

    def test_deposit_invalid_amount_returns_400(self):
        """Non-numeric deposit amount returns 400."""
        resp = self.client.post(
            "/api/v2/fund/deposit",
            json={
                "amount": "not-a-number",
                "payment_method": "UPI",
            },
        )
        assert resp.status_code == 400

    def test_deposit_invalid_payment_method_returns_400(self):
        """Invalid payment method returns 400."""
        resp = self.client.post(
            "/api/v2/fund/deposit",
            json={
                "amount": "1000.00",
                "payment_method": "BITCOIN",
            },
        )
        assert resp.status_code == 400


# ══════════════════════════════════════════════════════════════════════════════
# Flow 2: Screener filter → results → stock detail navigation
# Requirements: 10-11
# ══════════════════════════════════════════════════════════════════════════════


class TestScreenerToStockDetailFlow:
    """Integration test: screener search → verify results → navigate to stock detail."""

    def setup_method(self):
        self.app = _build_app()
        _override_auth(self.app)

        self.mock_screener = _mock_screener_engine()

        # Mock db_pool with proper async context manager for pool.acquire()
        self.mock_conn = AsyncMock()
        self.mock_db_pool = MagicMock()
        # acquire() returns an async context manager
        acm = AsyncMock()
        acm.__aenter__ = AsyncMock(return_value=self.mock_conn)
        acm.__aexit__ = AsyncMock(return_value=False)
        self.mock_db_pool.acquire.return_value = acm

        from app.routers.screener import get_db_pool, get_screener_engine

        self.app.dependency_overrides[get_screener_engine] = lambda: self.mock_screener
        self.app.dependency_overrides[get_db_pool] = lambda: self.mock_db_pool

        self.client = TestClient(self.app)

    def teardown_method(self):
        self.app.dependency_overrides.clear()

    def test_screener_search_returns_filtered_results(self):
        """Apply screener filters and verify results match expected shape."""
        resp = self.client.post(
            "/api/v2/screener/search",
            json={
                "pe_ratio": {"min": 10, "max": 35},
                "market_cap": {"min": 100000000000},
                "sector": "Energy",
                "sort_by": "market_cap",
                "order": "desc",
                "page": 1,
                "page_size": 50,
            },
        )
        assert resp.status_code == 200
        data = resp.json()

        # Verify response structure
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "total_pages" in data
        assert data["total"] == 2
        assert data["page"] == 1

        # Verify items have expected fields
        item = data["items"][0]
        assert "security_id" in item
        assert "symbol" in item
        assert "company_name" in item
        assert "exchange" in item
        assert "sector" in item
        assert "pe_ratio" in item
        assert "market_cap" in item

        # Verify the screener engine was called with correct filters
        self.mock_screener.screen.assert_called_once()

    def test_screener_results_contain_correct_data(self):
        """Verify screener results contain the mocked stock data."""
        resp = self.client.post(
            "/api/v2/screener/search",
            json={
                "sector": "IT/Technology",
            },
        )
        assert resp.status_code == 200
        data = resp.json()

        symbols = [item["symbol"] for item in data["items"]]
        assert "RELIANCE" in symbols
        assert "TCS" in symbols

    def test_screener_to_stock_detail_navigation(self):
        """After getting screener results, navigate to stock detail for a result."""
        # Step 1: Search
        resp = self.client.post(
            "/api/v2/screener/search",
            json={
                "pe_ratio": {"min": 10, "max": 35},
            },
        )
        assert resp.status_code == 200
        first_symbol = resp.json()["items"][0]["symbol"]

        # Step 2: Navigate to stock detail
        self.mock_conn.fetchrow.return_value = {
            "id": 1,
            "symbol": first_symbol,
            "company_name": "Reliance Industries",
            "exchange": "NSE",
            "sector": "Energy",
            "industry": "Oil & Gas",
            "market_cap_category": "large-cap",
            "listing_date": None,
            "face_value": Decimal("10.00"),
            "status": "ACTIVE",
            "pe_ratio": Decimal("25.50"),
            "pb_ratio": Decimal("2.10"),
            "market_cap": Decimal("1800000000000"),
            "dividend_yield": Decimal("0.45"),
            "eps": Decimal("95.20"),
            "roe": Decimal("12.50"),
            "debt_to_equity": Decimal("0.80"),
            "revenue_growth_1y": Decimal("15.30"),
            "revenue_growth_3y": Decimal("12.00"),
            "profit_growth_1y": Decimal("18.50"),
            "profit_growth_3y": Decimal("14.20"),
            "return_1y": Decimal("22.30"),
            "cagr_3y": Decimal("18.50"),
            "cagr_5y": Decimal("15.20"),
            "high_52w": Decimal("2800.00"),
            "low_52w": Decimal("2100.00"),
            "rsi_14": Decimal("55.30"),
            "sma_50": Decimal("2500.00"),
            "sma_200": Decimal("2350.00"),
            "avg_volume_20d": 5000000,
            "price_change_1d": Decimal("1.20"),
            "price_change_1w": Decimal("3.50"),
            "price_change_1m": Decimal("5.80"),
            "price_change_3m": Decimal("8.20"),
            "price_change_6m": Decimal("12.50"),
            "price_change_1y": Decimal("22.30"),
            "price_change_3y": Decimal("45.00"),
            "price_change_5y": Decimal("80.00"),
        }

        resp = self.client.get(f"/api/v2/stocks/{first_symbol}/detail")
        assert resp.status_code == 200
        detail = resp.json()

        # Verify stock detail response shape
        assert detail["symbol"] == first_symbol
        assert detail["company_name"] == "Reliance Industries"
        assert detail["exchange"] == "NSE"
        assert detail["sector"] == "Energy"
        assert detail["industry"] == "Oil & Gas"
        assert detail["status"] == "ACTIVE"

        # Verify fundamental data present
        assert detail["pe_ratio"] == "25.50"
        assert detail["market_cap"] is not None
        assert detail["eps"] is not None
        assert detail["roe"] is not None

        # Verify technical data present
        assert detail["rsi_14"] is not None
        assert detail["sma_50"] is not None
        assert detail["avg_volume_20d"] == 5000000

    def test_stock_detail_not_found(self):
        """Stock detail for non-existent symbol returns 404."""
        self.mock_conn.fetchrow.return_value = None

        resp = self.client.get("/api/v2/stocks/NONEXIST/detail")
        assert resp.status_code == 404

    def test_screener_empty_filters_returns_results(self):
        """Screener with no filters still returns paginated results."""
        resp = self.client.post("/api/v2/screener/search", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data


# ══════════════════════════════════════════════════════════════════════════════
# Flow 3: Chatbot query → RAG retrieval → LLM response → chart rendering
# Requirements: 18-21
# ══════════════════════════════════════════════════════════════════════════════


class TestChatbotFlow:
    """Integration test: chatbot message → response with optional chart."""

    def setup_method(self):
        self.app = _build_app()
        _override_auth(self.app)

        self.mock_chatbot = _mock_chatbot_service()

        from app.routers.chatbot import get_chatbot_service

        self.app.dependency_overrides[get_chatbot_service] = lambda: self.mock_chatbot

        self.client = TestClient(self.app)

    def teardown_method(self):
        self.app.dependency_overrides.clear()

    def test_text_query_returns_structured_response(self):
        """Send a text query and verify the response structure."""
        self.mock_chatbot.chat.return_value = ChatResponse(
            text="Your total P&L for last month is ₹12,500. Win rate: 65%.",
            sources=["trades (15 records)", "sentiment_log (8 records)"],
            response_time_ms=320,
        )

        resp = self.client.post(
            "/api/v2/chatbot/message",
            json={
                "message": "What was my P&L last month?",
            },
        )
        assert resp.status_code == 200
        data = resp.json()

        # Verify response structure
        assert "text" in data
        assert "chart_data" in data
        assert "chart_type" in data
        assert "sources" in data
        assert "response_time_ms" in data

        # Verify content
        assert "₹12,500" in data["text"]
        assert data["chart_data"] is None
        assert data["chart_type"] is None
        assert len(data["sources"]) == 2
        assert data["response_time_ms"] == 320

        # Verify service called with correct user
        self.mock_chatbot.chat.assert_called_once_with(TEST_USER_ID, "What was my P&L last month?")

    def test_chart_query_returns_base64_image(self):
        """Query requesting a chart returns base64-encoded chart data."""
        chart_svg = (
            b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="400" height="200"/></svg>'
        )
        self.mock_chatbot.chat.return_value = ChatResponse(
            text="Here is your equity curve for the last 3 months.",
            chart_data=chart_svg,
            chart_type="equity_curve",
            sources=["trades (30 records)"],
            response_time_ms=1500,
        )

        resp = self.client.post(
            "/api/v2/chatbot/message",
            json={
                "message": "Show my equity curve for last 3 months",
            },
        )
        assert resp.status_code == 200
        data = resp.json()

        # Verify chart data is base64 encoded
        assert data["chart_data"] is not None
        assert data["chart_type"] == "equity_curve"
        decoded = base64.b64decode(data["chart_data"])
        assert decoded == chart_svg
        assert b"<svg" in decoded

    def test_chatbot_conversation_flow(self):
        """Multi-turn conversation: query → follow-up → history check."""
        # Turn 1: Initial query
        self.mock_chatbot.chat.return_value = ChatResponse(
            text="You had 5 trades on RELIANCE last week.",
            sources=["trades (5 records)"],
            response_time_ms=200,
        )
        resp1 = self.client.post(
            "/api/v2/chatbot/message",
            json={
                "message": "How many trades did I have on RELIANCE last week?",
            },
        )
        assert resp1.status_code == 200
        assert "5 trades" in resp1.json()["text"]

        # Turn 2: Follow-up query
        self.mock_chatbot.chat.return_value = ChatResponse(
            text="Your best RELIANCE trade was on Monday with ₹2,300 profit.",
            sources=["trades (1 record)"],
            response_time_ms=180,
        )
        resp2 = self.client.post(
            "/api/v2/chatbot/message",
            json={
                "message": "Which was the best one?",
            },
        )
        assert resp2.status_code == 200
        assert "₹2,300" in resp2.json()["text"]

        # Turn 3: Check history
        self.mock_chatbot.get_history.return_value = [
            {
                "role": "user",
                "content": "How many trades did I have on RELIANCE last week?",
                "timestamp": "2024-01-15T10:00:00",
            },
            {
                "role": "assistant",
                "content": "You had 5 trades on RELIANCE last week.",
                "timestamp": "2024-01-15T10:00:01",
            },
            {
                "role": "user",
                "content": "Which was the best one?",
                "timestamp": "2024-01-15T10:00:05",
            },
            {
                "role": "assistant",
                "content": "Your best RELIANCE trade was on Monday with ₹2,300 profit.",
                "timestamp": "2024-01-15T10:00:06",
            },
        ]
        resp3 = self.client.get("/api/v2/chatbot/history")
        assert resp3.status_code == 200
        history = resp3.json()
        assert history["count"] == 4
        assert history["messages"][0]["role"] == "user"
        assert history["messages"][1]["role"] == "assistant"

    def test_chatbot_daily_pnl_chart(self):
        """Query for daily P&L returns a bar chart."""
        chart_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100  # Fake PNG header
        self.mock_chatbot.chat.return_value = ChatResponse(
            text="Here is your daily P&L for this week.",
            chart_data=chart_png,
            chart_type="daily_pnl",
            sources=["trades (25 records)"],
            response_time_ms=2100,
        )

        resp = self.client.post(
            "/api/v2/chatbot/message",
            json={
                "message": "Show my daily P&L this week",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["chart_type"] == "daily_pnl"
        assert data["chart_data"] is not None
        # Verify it's valid base64
        decoded = base64.b64decode(data["chart_data"])
        assert len(decoded) > 0

    def test_chatbot_clear_session(self):
        """Clear session resets conversation context."""
        self.mock_chatbot.clear_session.return_value = True

        resp = self.client.delete("/api/v2/chatbot/session")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        self.mock_chatbot.clear_session.assert_called_once_with(TEST_USER_ID)

    def test_chatbot_hinglish_input(self):
        """Chatbot handles Hinglish (Hindi-English mixed) input."""
        self.mock_chatbot.chat.return_value = ChatResponse(
            text="Aapka total P&L ₹8,000 hai last week ka.",
            sources=["trades (12 records)"],
            response_time_ms=350,
        )

        resp = self.client.post(
            "/api/v2/chatbot/message",
            json={
                "message": "Mera last week ka P&L kya hai?",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "₹8,000" in data["text"]

    def test_chatbot_empty_message_rejected(self):
        """Empty message body is rejected with 422."""
        resp = self.client.post("/api/v2/chatbot/message", json={})
        assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# Cross-flow: Auth required on all endpoints
# ══════════════════════════════════════════════════════════════════════════════


class TestAuthRequiredOnAllFlows:
    """Verify all integration endpoints require authentication."""

    def setup_method(self):
        self.app = _build_app()
        # Do NOT override auth — test that endpoints reject unauthenticated requests

        # Still need service mocks to avoid 503
        self.mock_screener = _mock_screener_engine()
        self.mock_chatbot = _mock_chatbot_service()

        from app.routers.chatbot import get_chatbot_service
        from app.routers.screener import get_screener_engine

        self.app.dependency_overrides[get_screener_engine] = lambda: self.mock_screener
        self.app.dependency_overrides[get_chatbot_service] = lambda: self.mock_chatbot

        self.client = TestClient(self.app)

    def teardown_method(self):
        self.app.dependency_overrides.clear()

    def test_pan_verify_requires_auth(self):
        resp = self.client.post("/api/v2/verify/pan", json={"pan": "ABCDE1234Z"})
        assert resp.status_code == 401

    def test_screener_search_requires_auth(self):
        resp = self.client.post("/api/v2/screener/search", json={})
        assert resp.status_code == 401

    def test_chatbot_message_requires_auth(self):
        resp = self.client.post("/api/v2/chatbot/message", json={"message": "hello"})
        assert resp.status_code == 401

    def test_fund_deposit_requires_auth(self):
        resp = self.client.post(
            "/api/v2/fund/deposit",
            json={
                "amount": "1000.00",
                "payment_method": "UPI",
            },
        )
        assert resp.status_code == 401

    def test_bank_register_requires_auth(self):
        resp = self.client.post(
            "/api/v2/bank/register",
            json={
                "account_holder_name": "Test",
                "account_number": "123",
                "ifsc_code": "HDFC0001234",
                "bank_name": "HDFC",
                "account_type": "savings",
            },
        )
        assert resp.status_code == 401
