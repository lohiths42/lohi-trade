"""Property-based tests for fund management.

**Validates: Requirements 5.5, 6.1, 6.3, 6.8**

Property 9: Withdrawable balance invariant — withdrawable balance always equals
    total balance minus blocked margin, never negative.

Property 10: Deposit/withdrawal limits — deposits outside ₹100-₹10,00,000
    rejected; withdrawals exceeding daily ₹25,00,000 rejected.

Uses Hypothesis with in-memory mocks for deterministic, fast property testing
without a real database or payment gateway.
"""

import os
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

# Ensure encryption key is set before importing service
if "PAN_ENCRYPTION_KEY" not in os.environ:
    from cryptography.fernet import Fernet
    os.environ["PAN_ENCRYPTION_KEY"] = Fernet.generate_key().decode()

from app.services.fund_service import (
    FundService,
    TransactionStatus,
    MIN_DEPOSIT,
    MAX_DEPOSIT,
    MIN_WITHDRAWAL,
    DAILY_MAX_WITHDRAWAL,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_service(db_pool=None) -> FundService:
    return FundService(
        db_pool=db_pool,
        payment_api_url="https://test.payment-gateway.co.in",
        payment_api_key="test-key",
    )


def _make_mock_pool():
    pool = MagicMock()
    conn = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = ctx
    return pool, conn


# ── Strategies ───────────────────────────────────────────────────────────────

# Positive Decimal amounts for balances and margins
positive_balances = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("99999999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

# Deposit amounts within valid range
valid_deposit_amounts = st.decimals(
    min_value=MIN_DEPOSIT,
    max_value=MAX_DEPOSIT,
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

# Deposit amounts below minimum
below_min_deposit_amounts = st.decimals(
    min_value=Decimal("-10000"),
    max_value=MIN_DEPOSIT - Decimal("0.01"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

# Deposit amounts above maximum
above_max_deposit_amounts = st.decimals(
    min_value=MAX_DEPOSIT + Decimal("0.01"),
    max_value=Decimal("99999999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

# Daily withdrawal totals that leave room for more withdrawals
daily_totals_with_room = st.decimals(
    min_value=Decimal("0"),
    max_value=DAILY_MAX_WITHDRAWAL - MIN_WITHDRAWAL,
    places=2,
    allow_nan=False,
    allow_infinity=False,
)


# ── Property 9: Withdrawable balance invariant ──────────────────────────────


class TestWithdrawableBalanceInvariantProperty:
    """**Validates: Requirements 6.1**

    Property 9: Withdrawable balance invariant — withdrawable balance always
    equals total balance minus blocked margin, never negative.
    """

    @given(
        available_balance=positive_balances,
        blocked_margin=positive_balances,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_withdrawable_equals_balance_minus_margin(
        self, available_balance: Decimal, blocked_margin: Decimal
    ):
        """For any (available_balance, blocked_margin) pair, withdrawable balance
        must equal max(available_balance - blocked_margin, 0)."""
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(return_value={
            "available_balance": available_balance,
            "blocked_margin": blocked_margin,
        })
        svc = _make_service(db_pool=pool)

        result = await svc.get_withdrawable_balance("user-test")

        expected = max(available_balance - blocked_margin, Decimal("0"))
        assert result == expected, (
            f"Expected withdrawable={expected}, got {result} "
            f"(balance={available_balance}, margin={blocked_margin})"
        )

    @given(
        available_balance=positive_balances,
        blocked_margin=positive_balances,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_withdrawable_never_negative(
        self, available_balance: Decimal, blocked_margin: Decimal
    ):
        """Withdrawable balance must never be negative, regardless of
        available_balance and blocked_margin values."""
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(return_value={
            "available_balance": available_balance,
            "blocked_margin": blocked_margin,
        })
        svc = _make_service(db_pool=pool)

        result = await svc.get_withdrawable_balance("user-test")

        assert result >= Decimal("0"), (
            f"Withdrawable balance is negative: {result} "
            f"(balance={available_balance}, margin={blocked_margin})"
        )

    @given(balance=positive_balances)
    @settings(max_examples=50)
    @pytest.mark.asyncio
    async def test_zero_margin_means_full_balance_withdrawable(
        self, balance: Decimal
    ):
        """When blocked_margin is zero, withdrawable balance equals
        the full available_balance."""
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(return_value={
            "available_balance": balance,
            "blocked_margin": Decimal("0"),
        })
        svc = _make_service(db_pool=pool)

        result = await svc.get_withdrawable_balance("user-test")
        assert result == balance, (
            f"With zero margin, expected {balance}, got {result}"
        )

    @given(margin=st.decimals(
        min_value=Decimal("0.01"),
        max_value=Decimal("99999999.99"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    ))
    @settings(max_examples=50)
    @pytest.mark.asyncio
    async def test_margin_exceeding_balance_returns_zero(
        self, margin: Decimal
    ):
        """When blocked_margin exceeds available_balance, withdrawable
        balance must be exactly zero."""
        balance = margin - Decimal("0.01")
        if balance < Decimal("0"):
            balance = Decimal("0")

        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(return_value={
            "available_balance": balance,
            "blocked_margin": margin,
        })
        svc = _make_service(db_pool=pool)

        result = await svc.get_withdrawable_balance("user-test")
        assert result == Decimal("0"), (
            f"Expected 0 when margin ({margin}) > balance ({balance}), got {result}"
        )


# ── Property 10: Deposit/withdrawal limits ───────────────────────────────────


class TestDepositWithdrawalLimitsProperty:
    """**Validates: Requirements 5.5, 6.3, 6.8**

    Property 10: Deposit/withdrawal limits — deposits outside ₹100-₹10,00,000
    rejected; withdrawals exceeding daily ₹25,00,000 rejected.
    """

    # ── Deposit limit tests ──────────────────────────────────────────────

    @given(amount=valid_deposit_amounts)
    @settings(max_examples=100)
    def test_deposits_within_range_accepted(self, amount: Decimal):
        """Any deposit amount in [₹100, ₹10,00,000] must be accepted
        by validate_deposit_amount."""
        svc = _make_service()
        valid, error = svc.validate_deposit_amount(amount)
        assert valid is True, (
            f"Valid deposit ₹{amount} was rejected: {error}"
        )
        assert error is None

    @given(amount=below_min_deposit_amounts)
    @settings(max_examples=100)
    def test_deposits_below_minimum_rejected(self, amount: Decimal):
        """Any deposit amount below ₹100 must be rejected."""
        svc = _make_service()
        valid, error = svc.validate_deposit_amount(amount)
        assert valid is False, (
            f"Deposit ₹{amount} (below min ₹{MIN_DEPOSIT}) was accepted"
        )
        assert error is not None

    @given(amount=above_max_deposit_amounts)
    @settings(max_examples=100)
    def test_deposits_above_maximum_rejected(self, amount: Decimal):
        """Any deposit amount above ₹10,00,000 must be rejected."""
        svc = _make_service()
        valid, error = svc.validate_deposit_amount(amount)
        assert valid is False, (
            f"Deposit ₹{amount} (above max ₹{MAX_DEPOSIT}) was accepted"
        )
        assert error is not None

    def test_deposit_boundary_minimum_accepted(self):
        """Exact minimum deposit ₹100 must be accepted."""
        svc = _make_service()
        valid, error = svc.validate_deposit_amount(MIN_DEPOSIT)
        assert valid is True
        assert error is None

    def test_deposit_boundary_maximum_accepted(self):
        """Exact maximum deposit ₹10,00,000 must be accepted."""
        svc = _make_service()
        valid, error = svc.validate_deposit_amount(MAX_DEPOSIT)
        assert valid is True
        assert error is None

    def test_deposit_just_below_minimum_rejected(self):
        """₹99.99 must be rejected."""
        svc = _make_service()
        valid, error = svc.validate_deposit_amount(Decimal("99.99"))
        assert valid is False

    def test_deposit_just_above_maximum_rejected(self):
        """₹10,00,000.01 must be rejected."""
        svc = _make_service()
        valid, error = svc.validate_deposit_amount(Decimal("1000000.01"))
        assert valid is False

    # ── Withdrawal limit tests ───────────────────────────────────────────

    @given(amount=st.decimals(
        min_value=MIN_WITHDRAWAL,
        max_value=Decimal("9999999.99"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    ))
    @settings(max_examples=100)
    def test_withdrawals_at_or_above_minimum_accepted(self, amount: Decimal):
        """Any withdrawal amount >= ₹100 must pass validate_withdrawal_amount."""
        svc = _make_service()
        valid, error = svc.validate_withdrawal_amount(amount)
        assert valid is True, (
            f"Valid withdrawal ₹{amount} was rejected: {error}"
        )
        assert error is None

    @given(amount=st.decimals(
        min_value=Decimal("-10000"),
        max_value=MIN_WITHDRAWAL - Decimal("0.01"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    ))
    @settings(max_examples=100)
    def test_withdrawals_below_minimum_rejected(self, amount: Decimal):
        """Any withdrawal amount below ₹100 must be rejected."""
        svc = _make_service()
        valid, error = svc.validate_withdrawal_amount(amount)
        assert valid is False, (
            f"Withdrawal ₹{amount} (below min ₹{MIN_WITHDRAWAL}) was accepted"
        )
        assert error is not None

    @given(
        daily_total=st.decimals(
            min_value=Decimal("0"),
            max_value=DAILY_MAX_WITHDRAWAL - Decimal("0.01"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
        excess=st.decimals(
            min_value=Decimal("0.01"),
            max_value=Decimal("5000000"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_daily_limit_enforcement(
        self, daily_total: Decimal, excess: Decimal
    ):
        """When daily_total + withdrawal_amount > DAILY_MAX_WITHDRAWAL,
        the withdrawal must be rejected with a daily limit error."""
        # Construct withdrawal_amount that always exceeds the remaining limit
        remaining = DAILY_MAX_WITHDRAWAL - daily_total
        withdrawal_amount = remaining + excess
        # Ensure it's at least MIN_WITHDRAWAL
        assume(withdrawal_amount >= MIN_WITHDRAWAL)

        pool, conn = _make_mock_pool()
        call_count = 0

        async def mock_fetchrow(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # _get_verified_bank_account
                return {"id": "bank-1", "ifsc_code": "HDFC0001234",
                        "bank_name": "HDFC", "account_holder_name": "Test User"}
            elif call_count == 2:
                # get_withdrawable_balance — enough balance
                return {"available_balance": Decimal("99999999"),
                        "blocked_margin": Decimal("0")}
            elif call_count == 3:
                # _get_daily_withdrawal_total
                return {"total": daily_total}
            return None

        conn.fetchrow = AsyncMock(side_effect=mock_fetchrow)
        conn.execute = AsyncMock()
        svc = _make_service(db_pool=pool)

        result = await svc.initiate_withdrawal("user-test", withdrawal_amount, "bank-1")

        assert result.status.value == "FAILED", (
            f"Withdrawal ₹{withdrawal_amount} with daily total ₹{daily_total} "
            f"(sum=₹{daily_total + withdrawal_amount}) should be rejected "
            f"(limit=₹{DAILY_MAX_WITHDRAWAL})"
        )
        assert "daily withdrawal limit" in result.failure_reason.lower()

    @given(
        fraction=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    )
    @settings(max_examples=50)
    @pytest.mark.asyncio
    async def test_daily_limit_within_range_passes_step4(
        self, fraction: float
    ):
        """When daily_total + withdrawal_amount <= DAILY_MAX_WITHDRAWAL,
        the withdrawal must NOT be rejected at the daily limit step."""
        from unittest.mock import patch

        # Split DAILY_MAX_WITHDRAWAL between daily_total and withdrawal_amount
        total_budget = DAILY_MAX_WITHDRAWAL - MIN_WITHDRAWAL
        daily_total = (total_budget * Decimal(str(fraction))).quantize(Decimal("0.01"))
        withdrawal_amount = MIN_WITHDRAWAL  # Always use minimum to stay within limit

        pool, conn = _make_mock_pool()
        call_count = 0

        async def mock_fetchrow(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # _get_verified_bank_account
                return {"id": "bank-1", "ifsc_code": "HDFC0001234",
                        "bank_name": "HDFC", "account_holder_name": "Test User"}
            elif call_count == 2:
                # get_withdrawable_balance — enough balance
                return {"available_balance": Decimal("99999999"),
                        "blocked_margin": Decimal("0")}
            elif call_count == 3:
                # _get_daily_withdrawal_total
                return {"total": daily_total}
            return None

        conn.fetchrow = AsyncMock(side_effect=mock_fetchrow)
        conn.execute = AsyncMock()
        svc = _make_service(db_pool=pool)

        # Patch the payment gateway call to avoid real HTTP requests
        with patch.object(svc, "_call_payment_gateway", new_callable=AsyncMock) as mock_gw:
            mock_gw.return_value = {
                "transaction_ref": "ref-test",
                "status": "PROCESSING",
                "method": "NEFT",
            }
            result = await svc.initiate_withdrawal("user-test", withdrawal_amount, "bank-1")

        # It should NOT fail due to daily limit
        if result.status.value == "FAILED" and result.failure_reason:
            assert "daily withdrawal limit" not in result.failure_reason.lower(), (
                f"Withdrawal ₹{withdrawal_amount} with daily total ₹{daily_total} "
                f"(sum=₹{daily_total + withdrawal_amount}) should NOT be rejected "
                f"for daily limit (limit=₹{DAILY_MAX_WITHDRAWAL})"
            )

    def test_daily_limit_constant_is_25_lakh(self):
        """DAILY_MAX_WITHDRAWAL must equal ₹25,00,000."""
        assert DAILY_MAX_WITHDRAWAL == Decimal("2500000")

    def test_min_deposit_constant_is_100(self):
        """MIN_DEPOSIT must equal ₹100."""
        assert MIN_DEPOSIT == Decimal("100")

    def test_max_deposit_constant_is_10_lakh(self):
        """MAX_DEPOSIT must equal ₹10,00,000."""
        assert MAX_DEPOSIT == Decimal("1000000")

    def test_min_withdrawal_constant_is_100(self):
        """MIN_WITHDRAWAL must equal ₹100."""
        assert MIN_WITHDRAWAL == Decimal("100")
