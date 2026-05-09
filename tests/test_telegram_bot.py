"""
Unit tests for the Telegram Bot module.

Tests notification formatting, rate limiting, command handling,
and graceful degradation when Telegram is not configured.

Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6, 18.7
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from src.ui.telegram_bot import (
    TelegramNotifier,
    TelegramCommandHandler,
    RATE_LIMIT_WINDOW_SECONDS,
)
from src.utils.config import Config, TelegramConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_config(
    bot_token: str = "test-token",
    chat_id: str = "12345",
    rate_limit: int = 20,
) -> MagicMock:
    config = MagicMock(spec=Config)
    config.telegram = TelegramConfig(
        bot_token=bot_token,
        chat_id=chat_id,
        rate_limit_messages_per_hour=rate_limit,
    )
    config.capital = MagicMock()
    config.capital.total = 200_000.0
    return config


def _make_notifier(
    bot_token="test-token",
    chat_id="12345",
    rate_limit=20,
    now=None,
) -> TelegramNotifier:
    config = _make_config(bot_token, chat_id, rate_limit)
    if now is None:
        now = datetime(2024, 1, 15, 15, 45)
    return TelegramNotifier(config, now_fn=lambda: now)


# ---------------------------------------------------------------------------
# TelegramNotifier – configuration
# ---------------------------------------------------------------------------


class TestTelegramNotifierConfig:
    """Tests for notifier initialisation and config handling."""

    def test_initialises_with_valid_config(self):
        n = _make_notifier()
        assert n._bot_token == "test-token"
        assert n._chat_id == "12345"
        assert n._rate_limit == 20

    def test_missing_telegram_config_disables_notifications(self):
        config = MagicMock(spec=Config)
        # Remove telegram attribute entirely
        del config.telegram
        n = TelegramNotifier(config)
        assert n._bot_token is None
        assert n._chat_id is None

    def test_send_returns_false_when_not_configured(self):
        config = MagicMock(spec=Config)
        del config.telegram
        n = TelegramNotifier(config)
        assert n._send_message("hello") is False


# ---------------------------------------------------------------------------
# TelegramNotifier – message formatting
# ---------------------------------------------------------------------------


class TestTradeEntryNotification:
    """Tests for send_trade_entry formatting."""

    @patch("src.ui.telegram_bot.requests.post")
    def test_buy_entry_format(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        n = _make_notifier()
        result = n.send_trade_entry("RELIANCE", "BUY", 40, 2500.0, "Trend Following")
        assert result is True
        call_args = mock_post.call_args
        text = call_args[1]["json"]["text"] if "json" in call_args[1] else call_args[0][1]["text"]
        assert "🟢" in text
        assert "BUY" in text
        assert "RELIANCE" in text
        assert "2,500.00" in text
        assert "40" in text
        assert "Trend Following" in text

    @patch("src.ui.telegram_bot.requests.post")
    def test_sell_entry_format(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        n = _make_notifier()
        result = n.send_trade_entry("INFY", "SELL", 100, 1500.0, "Mean Reversion")
        assert result is True
        text = mock_post.call_args[1]["json"]["text"]
        assert "🔴" in text
        assert "SELL" in text
        assert "INFY" in text


class TestTradeExitNotification:
    """Tests for send_trade_exit formatting."""

    @patch("src.ui.telegram_bot.requests.post")
    def test_profitable_exit(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        n = _make_notifier()
        result = n.send_trade_exit(
            "RELIANCE", "BUY", 40, 2500.0, 2550.0, 2000.0, "45m"
        )
        assert result is True
        text = mock_post.call_args[1]["json"]["text"]
        assert "SELL" in text  # Exit side is opposite
        assert "RELIANCE" in text
        assert "2,550.00" in text
        assert "+₹2,000.00" in text
        assert "+2.0%" in text
        assert "45m" in text

    @patch("src.ui.telegram_bot.requests.post")
    def test_losing_exit(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        n = _make_notifier()
        result = n.send_trade_exit(
            "INFY", "BUY", 50, 1500.0, 1470.0, -1500.0, "30m"
        )
        assert result is True
        text = mock_post.call_args[1]["json"]["text"]
        assert "INFY" in text
        assert "1,500.00" in text
        assert "-2.0%" in text


class TestKillSwitchAlert:
    """Tests for send_kill_switch_alert."""

    @patch("src.ui.telegram_bot.requests.post")
    def test_kill_switch_alert_format(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        n = _make_notifier()
        result = n.send_kill_switch_alert("Daily loss limit")
        assert result is True
        text = mock_post.call_args[1]["json"]["text"]
        assert "🛑" in text
        assert "KILL SWITCH ACTIVATED" in text
        assert "Daily loss limit" in text


class TestDailyLossWarning:
    """Tests for send_daily_loss_warning."""

    @patch("src.ui.telegram_bot.requests.post")
    def test_loss_warning_format(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        n = _make_notifier()
        result = n.send_daily_loss_warning(-3200.0, -4000.0)
        assert result is True
        text = mock_post.call_args[1]["json"]["text"]
        assert "⚠️" in text
        assert "DAILY LOSS WARNING" in text
        assert "80.0%" in text


class TestDailySummary:
    """Tests for send_daily_summary."""

    @patch("src.ui.telegram_bot.requests.post")
    def test_daily_summary_format(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        n = _make_notifier()
        result = n.send_daily_summary(5000.0, 8, 62.5, 200_000.0)
        assert result is True
        text = mock_post.call_args[1]["json"]["text"]
        assert "📊" in text
        assert "Daily Summary" in text
        assert "+₹5,000.00" in text
        assert "+2.5%" in text
        assert "Trades: 8" in text
        assert "Win Rate: 62.5%" in text

    @patch("src.ui.telegram_bot.requests.post")
    def test_daily_summary_negative_pnl(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        n = _make_notifier()
        result = n.send_daily_summary(-3000.0, 5, 40.0, 200_000.0)
        assert result is True
        text = mock_post.call_args[1]["json"]["text"]
        assert "3,000.00" in text
        assert "-1.5%" in text


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


class TestRateLimiting:
    """Tests for message rate limiting."""

    @patch("src.ui.telegram_bot.requests.post")
    def test_messages_within_limit_are_sent(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        n = _make_notifier(rate_limit=5)
        for i in range(5):
            assert n._send_message(f"msg {i}") is True
        assert mock_post.call_count == 5

    @patch("src.ui.telegram_bot.requests.post")
    def test_messages_beyond_limit_are_dropped(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        n = _make_notifier(rate_limit=3)
        results = [n._send_message(f"msg {i}") for i in range(5)]
        assert results == [True, True, True, False, False]
        assert mock_post.call_count == 3

    @patch("src.ui.telegram_bot.requests.post")
    def test_rate_limit_resets_after_window(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        t0 = datetime(2024, 1, 15, 10, 0, 0)
        current_time = [t0]
        n = _make_notifier(rate_limit=2)
        n._now_fn = lambda: current_time[0]

        # Send 2 messages at t0
        assert n._send_message("msg 1") is True
        assert n._send_message("msg 2") is True
        assert n._send_message("msg 3") is False  # Rate limited

        # Advance time past the window
        current_time[0] = t0 + timedelta(seconds=RATE_LIMIT_WINDOW_SECONDS + 1)
        assert n._send_message("msg 4") is True  # Should work now

    def test_messages_sent_this_hour_property(self):
        n = _make_notifier(rate_limit=20)
        assert n.messages_sent_this_hour == 0


# ---------------------------------------------------------------------------
# HTTP error handling
# ---------------------------------------------------------------------------


class TestHTTPErrorHandling:
    """Tests for Telegram API error handling."""

    @patch("src.ui.telegram_bot.requests.post")
    def test_api_error_returns_false(self, mock_post):
        mock_post.return_value = MagicMock(status_code=400, text="Bad Request")
        n = _make_notifier()
        assert n._send_message("test") is False

    @patch("src.ui.telegram_bot.requests.post")
    def test_network_error_returns_false(self, mock_post):
        import requests as req
        mock_post.side_effect = req.ConnectionError("timeout")
        n = _make_notifier()
        assert n._send_message("test") is False

    @patch("src.ui.telegram_bot.requests.post")
    def test_sends_to_correct_url(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        n = _make_notifier(bot_token="MY_TOKEN", chat_id="999")
        n._send_message("hello")
        url = mock_post.call_args[0][0]
        assert url == "https://api.telegram.org/botMY_TOKEN/sendMessage"
        payload = mock_post.call_args[1]["json"]
        assert payload["chat_id"] == "999"
        assert payload["text"] == "hello"


# ---------------------------------------------------------------------------
# TelegramCommandHandler
# ---------------------------------------------------------------------------


class TestCommandHandler:
    """Tests for bot command handling."""

    @patch("src.ui.telegram_bot.requests.post")
    def test_handle_help(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        n = _make_notifier()
        handler = TelegramCommandHandler(n)
        text = handler.handle_help()
        assert "/status" in text
        assert "/pnl" in text
        assert "/killswitch" in text
        assert "/help" in text

    @patch("src.ui.telegram_bot.requests.post")
    def test_handle_killswitch_activates(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        n = _make_notifier()
        ks = MagicMock()
        handler = TelegramCommandHandler(n, kill_switch=ks)
        text = handler.handle_killswitch()
        ks.activate.assert_called_once()
        assert "activated" in text.lower()

    @patch("src.ui.telegram_bot.requests.post")
    def test_handle_killswitch_no_kill_switch(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        n = _make_notifier()
        handler = TelegramCommandHandler(n, kill_switch=None)
        text = handler.handle_killswitch()
        assert "not available" in text.lower()

    @patch("src.ui.telegram_bot.requests.post")
    def test_handle_status_with_kill_switch(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        n = _make_notifier()
        ks = MagicMock()
        ks.is_active.return_value = False
        handler = TelegramCommandHandler(n, kill_switch=ks)
        text = handler.handle_status()
        assert "Inactive" in text

    @patch("src.ui.telegram_bot.requests.post")
    def test_handle_status_kill_switch_active(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        n = _make_notifier()
        ks = MagicMock()
        ks.is_active.return_value = True
        ks.get_reason.return_value = "Daily loss"
        handler = TelegramCommandHandler(n, kill_switch=ks)
        text = handler.handle_status()
        assert "ACTIVE" in text
        assert "Daily loss" in text

    @patch("src.ui.telegram_bot.requests.post")
    def test_handle_pnl_with_db(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        n = _make_notifier()
        db = MagicMock()
        conn = MagicMock()
        row = MagicMock()
        row.__getitem__ = lambda self, key: {
            "total": 5000.0, "trades": 8
        }.get(key, 0)
        cursor = MagicMock()
        cursor.fetchone.return_value = row
        conn.execute.return_value = cursor
        db.connect_sqlite.return_value = conn
        handler = TelegramCommandHandler(n, db_manager=db)
        text = handler.handle_pnl()
        assert "P&L" in text
