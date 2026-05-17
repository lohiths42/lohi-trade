"""Telegram Bot for LOHI-TRADE notifications and commands.

Provides:
- Trade entry/exit notifications with formatted messages
- Kill switch activation alerts
- Daily loss limit warnings
- Daily summary at 3:45 PM
- Bot commands: /status, /pnl, /killswitch, /help
- Rate limiting: max 20 messages per hour

Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6, 18.7
"""

from collections import deque
from collections.abc import Callable
from datetime import datetime

import requests

from src.utils.logger import get_logger

logger = get_logger("TelegramBot")

# Default rate limit
DEFAULT_RATE_LIMIT = 20
RATE_LIMIT_WINDOW_SECONDS = 3600  # 1 hour


class TelegramNotifier:
    """Send formatted notifications to a Telegram chat.

    Uses the Telegram Bot API via simple HTTP POST requests.
    Enforces a per-hour rate limit (default 20 messages/hour).
    """

    def __init__(
        self,
        config,
        db_manager=None,
        redis_client=None,
        kill_switch=None,
        *,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._db = db_manager
        self._redis = redis_client
        self._kill_switch = kill_switch
        self._now_fn = now_fn or datetime.now

        # Telegram config
        try:
            self._bot_token: str | None = config.telegram.bot_token
            self._chat_id: str | None = config.telegram.chat_id
            self._rate_limit: int = getattr(
                config.telegram,
                "rate_limit_messages_per_hour",
                DEFAULT_RATE_LIMIT,
            )
        except AttributeError:
            logger.warning("Telegram configuration not available – notifications disabled")
            self._bot_token = None
            self._chat_id = None
            self._rate_limit = DEFAULT_RATE_LIMIT

        # Rate limiter: timestamps of sent messages within the window
        self._sent_timestamps: deque = deque()

        logger.info(
            f"TelegramNotifier initialised: "
            f"token={'set' if self._bot_token else 'missing'}, "
            f"chat_id={'set' if self._chat_id else 'missing'}, "
            f"rate_limit={self._rate_limit}/hr",
        )

    # ------------------------------------------------------------------
    # Public notification methods
    # ------------------------------------------------------------------

    def send_trade_entry(
        self,
        symbol: str,
        side: str,
        quantity: int,
        price: float,
        strategy: str,
    ) -> bool:
        """Send a trade entry notification.

        Format: 🟢 BUY RELIANCE @ ₹2,500 | Qty: 40 | Strategy: Trend Following
        """
        emoji = "🟢" if side.upper() == "BUY" else "🔴"
        text = (
            f"{emoji} {side.upper()} {symbol} @ ₹{price:,.2f} | "
            f"Qty: {quantity} | Strategy: {strategy}"
        )
        return self._send_message(text)

    def send_trade_exit(
        self,
        symbol: str,
        side: str,
        quantity: int,
        entry_price: float,
        exit_price: float,
        pnl: float,
        holding_period: str,
    ) -> bool:
        """Send a trade exit notification.

        Format: 🔴 SELL RELIANCE @ ₹2,550 | P&L: +₹2,000 (+2.0%) | Hold: 45m
        """
        pnl_pct = ((exit_price - entry_price) / entry_price) * 100
        if side.upper() == "SELL":
            # If original side was SELL (short), invert P&L %
            pnl_pct = -pnl_pct

        pnl_sign = "+" if pnl >= 0 else ""
        pct_sign = "+" if pnl_pct >= 0 else ""
        exit_side = "SELL" if side.upper() == "BUY" else "BUY"
        emoji = "🔴" if exit_side == "SELL" else "🟢"

        text = (
            f"{emoji} {exit_side} {symbol} @ ₹{exit_price:,.2f} | "
            f"P&L: {pnl_sign}₹{pnl:,.2f} ({pct_sign}{pnl_pct:.1f}%) | "
            f"Hold: {holding_period}"
        )
        return self._send_message(text)

    def send_kill_switch_alert(self, reason: str) -> bool:
        """Send kill switch activation notification."""
        text = f"🛑 KILL SWITCH ACTIVATED | Reason: {reason}"
        return self._send_message(text)

    def send_daily_loss_warning(self, current_loss: float, limit: float) -> bool:
        """Send daily loss limit warning (80% threshold)."""
        pct = (abs(current_loss) / abs(limit)) * 100 if limit != 0 else 0
        text = (
            f"⚠️ DAILY LOSS WARNING | "
            f"Current: ₹{current_loss:,.2f} | "
            f"Limit: ₹{limit:,.2f} | "
            f"Usage: {pct:.1f}%"
        )
        return self._send_message(text)

    def send_daily_summary(
        self,
        total_pnl: float,
        num_trades: int,
        win_rate: float,
        capital: float,
    ) -> bool:
        """Send daily summary notification (3:45 PM).

        Format: 📊 Daily Summary | P&L: +₹5,000 (+2.5%) | Trades: 8 | Win Rate: 62.5%
        """
        pnl_pct = (total_pnl / capital) * 100 if capital != 0 else 0
        pnl_sign = "+" if total_pnl >= 0 else ""
        pct_sign = "+" if pnl_pct >= 0 else ""
        text = (
            f"📊 Daily Summary | "
            f"P&L: {pnl_sign}₹{total_pnl:,.2f} ({pct_sign}{pnl_pct:.1f}%) | "
            f"Trades: {num_trades} | "
            f"Win Rate: {win_rate:.1f}%"
        )
        return self._send_message(text)

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def _is_rate_limited(self) -> bool:
        """Return True if the rate limit has been reached."""
        now = self._now_fn()
        now_ts = now.timestamp()
        cutoff = now_ts - RATE_LIMIT_WINDOW_SECONDS

        # Evict old timestamps
        while self._sent_timestamps and self._sent_timestamps[0] < cutoff:
            self._sent_timestamps.popleft()

        return len(self._sent_timestamps) >= self._rate_limit

    def _record_sent(self) -> None:
        """Record that a message was sent."""
        now_ts = self._now_fn().timestamp()
        self._sent_timestamps.append(now_ts)

    @property
    def messages_sent_this_hour(self) -> int:
        """Number of messages sent in the current rate-limit window."""
        now_ts = self._now_fn().timestamp()
        cutoff = now_ts - RATE_LIMIT_WINDOW_SECONDS
        while self._sent_timestamps and self._sent_timestamps[0] < cutoff:
            self._sent_timestamps.popleft()
        return len(self._sent_timestamps)

    # ------------------------------------------------------------------
    # Core send
    # ------------------------------------------------------------------

    def _send_message(self, text: str) -> bool:
        """Send a message via Telegram Bot API with rate limiting.

        Returns True if the message was sent (or would be sent when
        token/chat_id are configured), False if rate-limited or failed.
        """
        if not self._bot_token or not self._chat_id:
            logger.warning("Telegram not configured – skipping message")
            return False

        if self._is_rate_limited():
            logger.warning(
                f"Rate limit reached ({self._rate_limit}/hr) – dropping message: {text[:80]}",
            )
            return False

        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "HTML",
        }

        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                self._record_sent()
                logger.info(f"Telegram message sent: {text[:80]}")
                return True
            logger.error(
                f"Telegram API error {resp.status_code}: {resp.text[:200]}",
            )
            return False
        except requests.RequestException as exc:
            logger.error(f"Telegram send failed: {exc}")
            return False


class TelegramCommandHandler:
    """Handle incoming Telegram bot commands.

    Supported commands:
    - /status  – open positions and current P&L
    - /pnl     – today's P&L breakdown
    - /killswitch – activate the kill switch
    - /help    – list available commands
    """

    def __init__(
        self,
        notifier: TelegramNotifier,
        db_manager=None,
        redis_client=None,
        kill_switch=None,
    ) -> None:
        self._notifier = notifier
        self._db = db_manager
        self._redis = redis_client
        self._kill_switch = kill_switch

    def handle_status(self) -> str:
        """Return a status summary of open positions and P&L."""
        lines = ["📋 *Status*"]

        # Kill switch
        if self._kill_switch:
            active = self._kill_switch.is_active()
            reason = self._kill_switch.get_reason() or ""
            if active:
                lines.append(f"🛑 Kill Switch: ACTIVE ({reason})")
            else:
                lines.append("✅ Kill Switch: Inactive")

        # Open positions from DB
        if self._db:
            try:
                conn = self._db.connect_sqlite()
                cur = conn.execute(
                    "SELECT symbol, side, quantity, entry_price "
                    "FROM trades WHERE exit_time IS NULL",
                )
                rows = cur.fetchall()
                if rows:
                    lines.append(f"\nOpen positions: {len(rows)}")
                    for r in rows:
                        lines.append(
                            f"  {r['symbol']} {r['side']} "
                            f"x{r['quantity']} @ ₹{float(r['entry_price']):,.2f}",
                        )
                else:
                    lines.append("\nNo open positions")
            except Exception as exc:
                lines.append(f"\n⚠️ DB error: {exc}")

        text = "\n".join(lines)
        self._notifier._send_message(text)
        return text

    def handle_pnl(self) -> str:
        """Return today's P&L breakdown."""
        lines = ["💰 *Today's P&L*"]

        if self._db:
            try:
                conn = self._db.connect_sqlite()
                today = self._notifier._now_fn().strftime("%Y-%m-%d")
                cur = conn.execute(
                    "SELECT COALESCE(SUM(realized_pnl), 0) AS total, "
                    "COUNT(*) AS trades "
                    "FROM trades WHERE DATE(exit_time) = ? "
                    "AND realized_pnl IS NOT NULL",
                    (today,),
                )
                row = cur.fetchone()
                total = float(row["total"]) if row else 0.0
                trades = int(row["trades"]) if row else 0
                lines.append(f"Realized P&L: ₹{total:,.2f}")
                lines.append(f"Closed trades: {trades}")
            except Exception as exc:
                lines.append(f"⚠️ DB error: {exc}")

        text = "\n".join(lines)
        self._notifier._send_message(text)
        return text

    def handle_killswitch(self) -> str:
        """Activate the kill switch via Telegram command."""
        if self._kill_switch:
            self._kill_switch.activate("Manual activation via Telegram /killswitch")
            text = "🛑 Kill switch activated via Telegram"
        else:
            text = "⚠️ Kill switch not available"
        self._notifier._send_message(text)
        return text

    def handle_help(self) -> str:
        """Return list of available commands."""
        text = (
            "🤖 *LOHI-TRADE Bot Commands*\n"
            "/status  – Open positions & system status\n"
            "/pnl     – Today's P&L breakdown\n"
            "/killswitch – Activate kill switch\n"
            "/help    – Show this help message"
        )
        self._notifier._send_message(text)
        return text
