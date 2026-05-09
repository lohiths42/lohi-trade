"""
Property-based tests for the Telegram Bot module.

Property 69: Telegram Trade Notifications
For any trade entry/exit, a notification should be sent with all
required fields (symbol, side, quantity, price/P&L).

Requirements: 18.1, 18.2, 18.7
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from src.ui.telegram_bot import TelegramNotifier
from src.utils.config import Config, TelegramConfig


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

_symbol = st.sampled_from([
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
    "SBIN", "BHARTIARTL", "ITC", "KOTAKBANK", "LT",
    "HINDUNILVR", "BAJFINANCE", "MARUTI", "AXISBANK", "WIPRO",
])
_side = st.sampled_from(["BUY", "SELL"])
_quantity = st.integers(min_value=1, max_value=5000)
_price = st.floats(min_value=10.0, max_value=100_000.0,
                   allow_nan=False, allow_infinity=False)
_pnl = st.floats(min_value=-500_000.0, max_value=500_000.0,
                 allow_nan=False, allow_infinity=False)
_strategy = st.sampled_from([
    "Mean Reversion", "Trend Following", "Opening Range Breakout",
])
_holding = st.sampled_from(["5m", "15m", "30m", "45m", "1h", "2h", "3h"])
_capital = st.floats(min_value=50_000.0, max_value=1_000_000.0,
                     allow_nan=False, allow_infinity=False)
_win_rate = st.floats(min_value=0.0, max_value=100.0,
                      allow_nan=False, allow_infinity=False)
_num_trades = st.integers(min_value=0, max_value=100)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_notifier(rate_limit: int = 1000) -> TelegramNotifier:
    """Create a notifier with a high rate limit for property testing."""
    config = MagicMock(spec=Config)
    config.telegram = TelegramConfig(
        bot_token="test-token",
        chat_id="12345",
        rate_limit_messages_per_hour=rate_limit,
    )
    now = datetime(2024, 1, 15, 10, 30)
    return TelegramNotifier(config, now_fn=lambda: now)


# ---------------------------------------------------------------------------
# Property 69: Telegram Trade Notifications
# For any trade entry/exit, a notification is sent containing all
# required fields: symbol, side, quantity, price (and P&L for exits).
# ---------------------------------------------------------------------------


@given(
    symbol=_symbol,
    side=_side,
    quantity=_quantity,
    price=_price,
    strategy=_strategy,
)
@settings(max_examples=25)
@patch("src.ui.telegram_bot.requests.post")
def test_prop_69_trade_entry_contains_all_fields(
    mock_post, symbol, side, quantity, price, strategy
):
    """Property 69: Trade entry notification contains symbol, side, qty, price, strategy."""
    mock_post.return_value = MagicMock(status_code=200)
    n = _make_notifier()

    result = n.send_trade_entry(symbol, side, quantity, price, strategy)
    assert result is True

    text = mock_post.call_args[1]["json"]["text"]
    assert symbol in text
    assert side.upper() in text
    assert str(quantity) in text
    assert f"{price:,.2f}" in text
    assert strategy in text


@given(
    symbol=_symbol,
    side=_side,
    quantity=_quantity,
    entry_price=_price,
    pnl=_pnl,
    holding=_holding,
)
@settings(max_examples=25)
@patch("src.ui.telegram_bot.requests.post")
def test_prop_69_trade_exit_contains_all_fields(
    mock_post, symbol, side, quantity, entry_price, pnl, holding
):
    """Property 69: Trade exit notification contains symbol, exit price, P&L, holding."""
    # Derive a valid exit price from entry + pnl/qty
    assume(quantity > 0)
    assume(entry_price > 0)
    exit_price = entry_price + (pnl / quantity)
    assume(exit_price > 0)

    mock_post.return_value = MagicMock(status_code=200)
    n = _make_notifier()

    result = n.send_trade_exit(
        symbol, side, quantity, entry_price, exit_price, pnl, holding
    )
    assert result is True

    text = mock_post.call_args[1]["json"]["text"]
    assert symbol in text
    assert f"{exit_price:,.2f}" in text
    assert f"{abs(pnl):,.2f}" in text
    assert holding in text


# ---------------------------------------------------------------------------
# Property 69 (rate limiting aspect): Messages beyond rate limit are dropped
# ---------------------------------------------------------------------------


@given(
    num_messages=st.integers(min_value=1, max_value=50),
    rate_limit=st.integers(min_value=1, max_value=30),
)
@settings(max_examples=25)
@patch("src.ui.telegram_bot.requests.post")
def test_prop_69_rate_limit_enforced(mock_post, num_messages, rate_limit):
    """Property 69 (rate limit): At most rate_limit messages sent per hour."""
    mock_post.return_value = MagicMock(status_code=200)
    n = _make_notifier(rate_limit=rate_limit)

    sent_count = 0
    for i in range(num_messages):
        if n._send_message(f"msg {i}"):
            sent_count += 1

    assert sent_count == min(num_messages, rate_limit)
    assert sent_count <= rate_limit


# ---------------------------------------------------------------------------
# Property 69 (daily summary): Summary contains P&L, trades, win rate
# ---------------------------------------------------------------------------


@given(
    total_pnl=_pnl,
    num_trades=_num_trades,
    win_rate=_win_rate,
    capital=_capital,
)
@settings(max_examples=25)
@patch("src.ui.telegram_bot.requests.post")
def test_prop_69_daily_summary_contains_all_fields(
    mock_post, total_pnl, num_trades, win_rate, capital
):
    """Property 69: Daily summary contains P&L, trade count, win rate."""
    mock_post.return_value = MagicMock(status_code=200)
    n = _make_notifier()

    result = n.send_daily_summary(total_pnl, num_trades, win_rate, capital)
    assert result is True

    text = mock_post.call_args[1]["json"]["text"]
    assert "Daily Summary" in text
    assert f"{abs(total_pnl):,.2f}" in text
    assert f"Trades: {num_trades}" in text
    assert f"Win Rate: {win_rate:.1f}%" in text
