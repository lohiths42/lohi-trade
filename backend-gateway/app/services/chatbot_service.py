"""Gen AI Chatbot Service — LLM-powered conversational assistant with RAG.

Provides ChatbotService (orchestrator), LLMClient (LLM API wrapper),
ChartGenerator (matplotlib chart generation), and TradingQueryHandler
(structured trading data queries) for the AI chatbot feature.

Conversation context is stored in Redis with 1-hour TTL (max 20 exchanges).
RAG retrieval queries the authenticated user's own trades, sentiment logs,
and signal history from PostgreSQL.

Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6, 18.7, 19.1, 19.2, 19.3, 19.4, 19.5, 19.6
"""

import json
import logging
import math
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

MAX_CONVERSATION_EXCHANGES = 20
REDIS_CHAT_TTL_SECONDS = 3600  # 1 hour
REDIS_CHAT_KEY_PREFIX = "chat:"
DEFAULT_MAX_TOKENS = 1024
LLM_TEXT_TIMEOUT_SECONDS = 5
LLM_CHART_TIMEOUT_SECONDS = 10

SYSTEM_PROMPT = (
    "You are Lohi-TRADE AI Assistant, a helpful trading chatbot. "
    "You answer questions about the user's own trading data, performance, "
    "and market activity. You support English and Hinglish (Hindi-English mixed) input. "
    "If you do not have sufficient data to answer a question, clearly state that "
    "rather than speculating. Never reveal or reference other users' data."
)

NO_DATA_RESPONSE = (
    "I don't have sufficient data to answer that question. "
    "Please try a more specific query about your trades, performance, or positions."
)


# ── Data classes ─────────────────────────────────────────────────────────────


class MessageRole(str, Enum):
    """Role of a message in the conversation."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass
class Message:
    """A single message in a conversation."""

    role: MessageRole
    content: str
    timestamp: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "role": self.role.value if isinstance(self.role, MessageRole) else self.role,
            "content": self.content,
            "timestamp": self.timestamp or datetime.now(timezone.utc).isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Message":
        role_val = data.get("role", "user")
        try:
            role = MessageRole(role_val)
        except ValueError:
            role = MessageRole.USER
        return cls(
            role=role,
            content=data.get("content", ""),
            timestamp=data.get("timestamp"),
        )


@dataclass
class RAGContext:
    """Context retrieved from the user's data for RAG."""

    trades: list[dict] = field(default_factory=list)
    sentiment_logs: list[dict] = field(default_factory=list)
    signals: list[dict] = field(default_factory=list)
    summary: str = ""

    @property
    def has_data(self) -> bool:
        return bool(self.trades or self.sentiment_logs or self.signals)

    def to_context_string(self) -> str:
        """Format RAG context as a string for the LLM prompt."""
        parts = []
        if self.trades:
            parts.append(f"Recent trades ({len(self.trades)}):")
            for t in self.trades[:10]:
                parts.append(f"  - {json.dumps(t, default=str)}")
        if self.sentiment_logs:
            parts.append(f"Sentiment logs ({len(self.sentiment_logs)}):")
            for s in self.sentiment_logs[:10]:
                parts.append(f"  - {json.dumps(s, default=str)}")
        if self.signals:
            parts.append(f"Signal history ({len(self.signals)}):")
            for sig in self.signals[:10]:
                parts.append(f"  - {json.dumps(sig, default=str)}")
        if self.summary:
            parts.append(f"Summary: {self.summary}")
        return "\n".join(parts) if parts else "No relevant data found."


@dataclass
class ChatResponse:
    """Response from the chatbot."""

    text: str
    chart_data: Optional[bytes] = None
    chart_type: Optional[str] = None
    sources: list[str] = field(default_factory=list)
    response_time_ms: int = 0


# ── LLM Client ──────────────────────────────────────────────────────────────


class LLMClient:
    """Lightweight LLM API wrapper. Supports OpenAI GPT-4o-mini and Llama 3.

    The client is provider-agnostic: it accepts an ``api_key``, ``api_base``
    (URL), and ``model`` name.  For OpenAI, use the default base; for Llama 3
    self-hosted or via a compatible provider, supply the appropriate base URL.
    """

    def __init__(
        self,
        api_key: str = "",
        api_base: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini",
        timeout: float = LLM_TEXT_TIMEOUT_SECONDS,
    ):
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = model
        self.timeout = timeout

    async def complete(
        self,
        messages: list[Message],
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> str:
        """Send messages to LLM API and return the assistant response text.

        Target <5s for text-only responses.  Uses httpx for async HTTP.
        Falls back to a polite error message on failure.
        """
        if not self.api_key:
            logger.warning("LLM API key not configured — returning fallback")
            return self._fallback_response(messages)

        payload = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            "max_tokens": max_tokens,
            "temperature": 0.3,
        }

        try:
            import httpx

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.api_base}/chat/completions",
                    json=payload,
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except Exception as exc:
            logger.error("LLM API call failed: %s", exc)
            return self._fallback_response(messages)

    @staticmethod
    def _fallback_response(messages: list[Message]) -> str:
        """Generate a basic fallback when the LLM API is unavailable."""
        last_user_msg = ""
        for m in reversed(messages):
            if m.role == MessageRole.USER:
                last_user_msg = m.content
                break
        if last_user_msg:
            return (
                "I'm currently unable to process your request through the AI model. "
                "Please try again shortly, or check your trading dashboard directly."
            )
        return "I'm here to help with your trading questions. How can I assist you?"


# ── Chart Generator ──────────────────────────────────────────────────────────


class ChartGenerator:
    """Lightweight chart generation using matplotlib (backend only).

    Generates SVG charts for equity curves, daily P&L, strategy
    comparison, and candlestick charts.  Theme-aware (dark/light).

    Requirements: 20.1, 20.2, 20.3, 20.4, 20.5, 20.6, 20.7
    """

    # ── Theme configuration ──────────────────────────────────────────────

    THEMES = {
        "dark": {
            "bg": "#1a1a2e",
            "fg": "#e0e0e0",
            "grid": "#2a2a4a",
            "accent": "#00d4ff",
            "positive": "#00e676",
            "negative": "#ff5252",
            "colors": ["#00d4ff", "#ff6ec7", "#ffd740", "#69f0ae", "#b388ff", "#ff8a65"],
            "candle_up": "#00e676",
            "candle_down": "#ff5252",
        },
        "light": {
            "bg": "#ffffff",
            "fg": "#212121",
            "grid": "#e0e0e0",
            "accent": "#1565c0",
            "positive": "#2e7d32",
            "negative": "#c62828",
            "colors": ["#1565c0", "#c2185b", "#f57f17", "#2e7d32", "#6a1b9a", "#d84315"],
            "candle_up": "#2e7d32",
            "candle_down": "#c62828",
        },
    }

    def _get_theme(self, theme: str) -> dict:
        """Return theme dict, defaulting to dark."""
        return self.THEMES.get(theme, self.THEMES["dark"])

    @staticmethod
    def _fig_to_svg(fig) -> bytes:
        """Render a matplotlib figure to SVG bytes and close it."""
        import io

        buf = io.BytesIO()
        fig.savefig(buf, format="svg", bbox_inches="tight", transparent=False)
        buf.seek(0)
        svg_bytes = buf.read()
        import matplotlib.pyplot as plt

        plt.close(fig)
        return svg_bytes

    def _apply_theme(self, fig, ax, t: dict, title: str = "") -> None:
        """Apply theme colors to figure and axes."""
        fig.patch.set_facecolor(t["bg"])
        ax.set_facecolor(t["bg"])
        ax.tick_params(colors=t["fg"], labelsize=8)
        ax.xaxis.label.set_color(t["fg"])
        ax.yaxis.label.set_color(t["fg"])
        ax.title.set_color(t["fg"])
        for spine in ax.spines.values():
            spine.set_color(t["grid"])
        ax.grid(True, color=t["grid"], alpha=0.3, linewidth=0.5)
        if title:
            ax.set_title(title, fontsize=11, fontweight="bold", color=t["fg"], pad=10)

    # ── Chart methods ────────────────────────────────────────────────────

    def equity_curve(self, data: list[dict], theme: str = "dark") -> bytes:
        """Generate equity curve line chart as SVG.

        Data: list of dicts with 'date' and 'equity' keys.
        Req 20.1: equity curve chart for performance-over-time queries.
        """
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt

        if not data:
            return self._empty_chart("No equity data available", theme)

        t = self._get_theme(theme)
        dates = []
        equities = []
        for d in data:
            dt = d.get("date")
            if isinstance(dt, str):
                try:
                    dt = datetime.fromisoformat(dt)
                except (ValueError, TypeError):
                    continue
            dates.append(dt)
            equities.append(float(d.get("equity", 0)))

        if not dates:
            return self._empty_chart("No valid equity data", theme)

        fig, ax = plt.subplots(figsize=(8, 4), dpi=100)
        self._apply_theme(fig, ax, t, "Equity Curve")

        ax.plot(dates, equities, color=t["accent"], linewidth=1.5, label="Equity")
        ax.fill_between(dates, equities, alpha=0.1, color=t["accent"])

        # Label start and end values
        ax.annotate(
            f"₹{equities[0]:,.0f}",
            xy=(dates[0], equities[0]),
            fontsize=7,
            color=t["fg"],
            ha="left",
        )
        ax.annotate(
            f"₹{equities[-1]:,.0f}",
            xy=(dates[-1], equities[-1]),
            fontsize=7,
            color=t["fg"],
            ha="right",
        )

        ax.set_xlabel("Date", fontsize=9)
        ax.set_ylabel("Equity (₹)", fontsize=9)
        ax.legend(
            loc="upper left", fontsize=8, facecolor=t["bg"], edgecolor=t["grid"], labelcolor=t["fg"]
        )

        if len(dates) > 10:
            ax.xaxis.set_major_locator(mdates.AutoDateLocator())
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        fig.autofmt_xdate(rotation=30, ha="right")

        return self._fig_to_svg(fig)

    def daily_pnl_bar(self, data: list[dict], theme: str = "dark") -> bytes:
        """Generate daily P&L bar chart as SVG.

        Data: list of dicts with 'date' and 'pnl' keys.
        Green for positive, red for negative.
        Req 20.2: daily P&L bar chart.
        """
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        if not data:
            return self._empty_chart("No P&L data available", theme)

        t = self._get_theme(theme)
        dates = []
        pnls = []
        for d in data:
            dt = d.get("date")
            if isinstance(dt, str):
                try:
                    dt = datetime.fromisoformat(dt)
                except (ValueError, TypeError):
                    continue
            dates.append(dt)
            pnls.append(float(d.get("pnl", 0)))

        if not dates:
            return self._empty_chart("No valid P&L data", theme)

        colors = [t["positive"] if p >= 0 else t["negative"] for p in pnls]

        fig, ax = plt.subplots(figsize=(8, 4), dpi=100)
        self._apply_theme(fig, ax, t, "Daily P&L")

        bars = ax.bar(range(len(dates)), pnls, color=colors, width=0.7, edgecolor="none")

        # Display values on bars
        for bar_obj, pnl in zip(bars, pnls):
            y_pos = bar_obj.get_height() if pnl >= 0 else bar_obj.get_y()
            va = "bottom" if pnl >= 0 else "top"
            ax.text(
                bar_obj.get_x() + bar_obj.get_width() / 2,
                y_pos,
                f"₹{pnl:,.0f}",
                ha="center",
                va=va,
                fontsize=6,
                color=t["fg"],
            )

        # X-axis labels
        if len(dates) <= 15:
            ax.set_xticks(range(len(dates)))
            labels = [d.strftime("%b %d") if hasattr(d, "strftime") else str(d) for d in dates]
            ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=7)
        else:
            step = max(1, len(dates) // 10)
            ax.set_xticks(range(0, len(dates), step))
            labels = [
                dates[i].strftime("%b %d") if hasattr(dates[i], "strftime") else str(dates[i])
                for i in range(0, len(dates), step)
            ]
            ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=7)

        ax.axhline(y=0, color=t["fg"], linewidth=0.5, alpha=0.5)
        ax.set_xlabel("Date", fontsize=9)
        ax.set_ylabel("P&L (₹)", fontsize=9)

        return self._fig_to_svg(fig)

    def strategy_comparison(self, data: list[dict], theme: str = "dark") -> bytes:
        """Generate strategy comparison grouped bar chart as SVG.

        Data: list of dicts with 'strategy', 'total_pnl', 'win_rate', 'trade_count' keys.
        Req 20.3: strategy comparison grouped bar chart.
        """
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        if not data:
            return self._empty_chart("No strategy data available", theme)

        t = self._get_theme(theme)
        strategies = [d.get("strategy", "Unknown") for d in data]
        total_pnls = [float(d.get("total_pnl", 0)) for d in data]
        win_rates = [float(d.get("win_rate", 0)) for d in data]
        trade_counts = [int(d.get("trade_count", 0)) for d in data]

        fig, axes = plt.subplots(1, 3, figsize=(12, 4), dpi=100)
        fig.patch.set_facecolor(t["bg"])
        fig.suptitle("Strategy Comparison", fontsize=12, fontweight="bold", color=t["fg"], y=1.02)

        metrics = [
            ("Total P&L (₹)", total_pnls, "₹{:,.0f}"),
            ("Win Rate (%)", win_rates, "{:.1f}%"),
            ("Trade Count", trade_counts, "{}"),
        ]

        x = np.arange(len(strategies))
        bar_width = 0.6

        for idx, (label, values, fmt) in enumerate(metrics):
            ax = axes[idx]
            ax.set_facecolor(t["bg"])
            ax.tick_params(colors=t["fg"], labelsize=7)
            for spine in ax.spines.values():
                spine.set_color(t["grid"])
            ax.grid(True, axis="y", color=t["grid"], alpha=0.3, linewidth=0.5)

            if label == "Total P&L (₹)":
                bar_colors = [t["positive"] if v >= 0 else t["negative"] for v in values]
            else:
                bar_colors = [t["colors"][i % len(t["colors"])] for i in range(len(values))]

            bars = ax.bar(x, values, bar_width, color=bar_colors, edgecolor="none")

            for bar_obj, val in zip(bars, values):
                y_pos = bar_obj.get_height()
                va = "bottom" if val >= 0 else "top"
                ax.text(
                    bar_obj.get_x() + bar_obj.get_width() / 2,
                    y_pos,
                    fmt.format(val),
                    ha="center",
                    va=va,
                    fontsize=7,
                    color=t["fg"],
                )

            ax.set_xticks(x)
            ax.set_xticklabels(strategies, rotation=30, ha="right", fontsize=7)
            ax.set_ylabel(label, fontsize=8, color=t["fg"])

            if label == "Total P&L (₹)":
                ax.axhline(y=0, color=t["fg"], linewidth=0.5, alpha=0.5)

        fig.tight_layout()
        return self._fig_to_svg(fig)

    def candlestick(
        self, ohlcv: list[dict], indicators: list[str] = None, theme: str = "dark"
    ) -> bytes:
        """Generate candlestick chart with optional indicator overlays as SVG.

        Data: list of dicts with 'date', 'open', 'high', 'low', 'close', 'volume' keys.
        Indicators: list of strings like 'SMA', 'EMA', 'RSI', 'MACD'.
        Req 20.4: candlestick chart with technical indicator overlays.
        """
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        if not ohlcv:
            return self._empty_chart("No OHLCV data available", theme)

        indicators = indicators or []
        t = self._get_theme(theme)

        # Parse data
        dates_raw = []
        opens = []
        highs = []
        lows = []
        closes = []
        volumes = []
        for d in ohlcv:
            dt = d.get("date")
            if isinstance(dt, str):
                try:
                    dt = datetime.fromisoformat(dt)
                except (ValueError, TypeError):
                    continue
            dates_raw.append(dt)
            opens.append(float(d.get("open", 0)))
            highs.append(float(d.get("high", 0)))
            lows.append(float(d.get("low", 0)))
            closes.append(float(d.get("close", 0)))
            volumes.append(float(d.get("volume", 0)))

        if not dates_raw:
            return self._empty_chart("No valid OHLCV data", theme)

        # Determine subplot layout based on indicators
        has_rsi = "RSI" in [i.upper() for i in indicators]
        has_macd = "MACD" in [i.upper() for i in indicators]
        overlay_indicators = [i for i in indicators if i.upper() not in ("RSI", "MACD")]

        n_subplots = 1
        height_ratios = [3]
        if has_rsi:
            n_subplots += 1
            height_ratios.append(1)
        if has_macd:
            n_subplots += 1
            height_ratios.append(1)

        fig, axes = plt.subplots(
            n_subplots,
            1,
            figsize=(10, 3 + n_subplots * 1.5),
            dpi=100,
            gridspec_kw={"height_ratios": height_ratios},
            sharex=True,
        )
        if n_subplots == 1:
            axes = [axes]

        ax_main = axes[0]
        fig.patch.set_facecolor(t["bg"])

        # Apply theme to all axes
        for ax in axes:
            ax.set_facecolor(t["bg"])
            ax.tick_params(colors=t["fg"], labelsize=7)
            for spine in ax.spines.values():
                spine.set_color(t["grid"])
            ax.grid(True, color=t["grid"], alpha=0.3, linewidth=0.5)

        ax_main.set_title(
            "Candlestick Chart", fontsize=11, fontweight="bold", color=t["fg"], pad=10
        )

        # Draw candlesticks
        x_indices = list(range(len(dates_raw)))
        body_width = 0.6
        wick_width = 0.15

        for i in range(len(dates_raw)):
            open_val, high_val, low_val, close_val = opens[i], highs[i], lows[i], closes[i]
            color = t["candle_up"] if close_val >= open_val else t["candle_down"]

            # Wick (high-low line)
            ax_main.plot(
                [i, i], [low_val, high_val], color=color, linewidth=wick_width * 5, solid_capstyle="round"
            )

            # Body
            body_bottom = min(open_val, close_val)
            body_height = abs(close_val - open_val) or (high_val - low_val) * 0.01  # tiny body for doji
            rect = plt.Rectangle(
                (i - body_width / 2, body_bottom),
                body_width,
                body_height,
                facecolor=color,
                edgecolor=color,
                linewidth=0.5,
            )
            ax_main.add_patch(rect)

        ax_main.set_xlim(-0.5, len(dates_raw) - 0.5)
        price_range = max(highs) - min(lows)
        ax_main.set_ylim(min(lows) - price_range * 0.05, max(highs) + price_range * 0.05)
        ax_main.set_ylabel("Price (₹)", fontsize=9, color=t["fg"])

        # Overlay indicators (SMA, EMA)
        legend_handles = []
        for idx_ind, ind_name in enumerate(overlay_indicators):
            ind_upper = ind_name.upper()
            color = t["colors"][(idx_ind + 1) % len(t["colors"])]
            if ind_upper in ("SMA", "EMA"):
                period = 20
                if len(closes) >= period:
                    if ind_upper == "SMA":
                        ma_values = self._compute_sma(closes, period)
                    else:
                        ma_values = self._compute_ema(closes, period)
                    valid_x = list(range(period - 1, len(closes)))
                    valid_y = ma_values[period - 1 :]
                    (line,) = ax_main.plot(
                        valid_x, valid_y, color=color, linewidth=1, label=f"{ind_name}({period})"
                    )
                    legend_handles.append(line)

        if legend_handles:
            ax_main.legend(
                handles=legend_handles,
                loc="upper left",
                fontsize=7,
                facecolor=t["bg"],
                edgecolor=t["grid"],
                labelcolor=t["fg"],
            )

        # RSI subplot
        subplot_idx = 1
        if has_rsi:
            ax_rsi = axes[subplot_idx]
            subplot_idx += 1
            rsi_values = self._compute_rsi(closes, 14)
            if rsi_values:
                valid_x = list(range(14, len(closes)))
                ax_rsi.plot(
                    valid_x, rsi_values[14:], color=t["accent"], linewidth=1, label="RSI(14)"
                )
                ax_rsi.axhline(y=70, color=t["negative"], linewidth=0.5, linestyle="--", alpha=0.7)
                ax_rsi.axhline(y=30, color=t["positive"], linewidth=0.5, linestyle="--", alpha=0.7)
                ax_rsi.set_ylim(0, 100)
                ax_rsi.set_ylabel("RSI", fontsize=8, color=t["fg"])
                ax_rsi.legend(
                    loc="upper left",
                    fontsize=7,
                    facecolor=t["bg"],
                    edgecolor=t["grid"],
                    labelcolor=t["fg"],
                )

        # MACD subplot
        if has_macd:
            ax_macd = axes[subplot_idx]
            macd_line, signal_line, histogram = self._compute_macd(closes)
            if macd_line:
                start = 33  # 26-period EMA needs 26 points, signal needs 9 more
                valid_x = list(range(start, len(closes)))
                ml = macd_line[start:]
                sl = signal_line[start:]
                hist = histogram[start:]
                ax_macd.plot(valid_x, ml, color=t["accent"], linewidth=1, label="MACD")
                ax_macd.plot(valid_x, sl, color=t["colors"][1], linewidth=1, label="Signal")
                hist_colors = [t["positive"] if h >= 0 else t["negative"] for h in hist]
                ax_macd.bar(valid_x, hist, color=hist_colors, width=0.6, alpha=0.6)
                ax_macd.axhline(y=0, color=t["fg"], linewidth=0.5, alpha=0.5)
                ax_macd.set_ylabel("MACD", fontsize=8, color=t["fg"])
                ax_macd.legend(
                    loc="upper left",
                    fontsize=7,
                    facecolor=t["bg"],
                    edgecolor=t["grid"],
                    labelcolor=t["fg"],
                )

        # X-axis labels on bottom subplot
        bottom_ax = axes[-1]
        if len(dates_raw) <= 20:
            bottom_ax.set_xticks(x_indices)
            labels = [d.strftime("%b %d") if hasattr(d, "strftime") else str(d) for d in dates_raw]
            bottom_ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=7)
        else:
            step = max(1, len(dates_raw) // 10)
            ticks = list(range(0, len(dates_raw), step))
            bottom_ax.set_xticks(ticks)
            labels = [
                (
                    dates_raw[i].strftime("%b %d")
                    if hasattr(dates_raw[i], "strftime")
                    else str(dates_raw[i])
                )
                for i in ticks
            ]
            bottom_ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=7)

        bottom_ax.set_xlabel("Date", fontsize=9, color=t["fg"])
        fig.tight_layout()
        return self._fig_to_svg(fig)

    # ── Helper: empty chart ──────────────────────────────────────────────

    def _empty_chart(self, message: str, theme: str) -> bytes:
        """Generate a minimal SVG with a 'no data' message."""
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        t = self._get_theme(theme)
        fig, ax = plt.subplots(figsize=(6, 3), dpi=100)
        fig.patch.set_facecolor(t["bg"])
        ax.set_facecolor(t["bg"])
        ax.text(
            0.5,
            0.5,
            message,
            ha="center",
            va="center",
            fontsize=12,
            color=t["fg"],
            transform=ax.transAxes,
        )
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)
        return self._fig_to_svg(fig)

    # ── Technical indicator computations ─────────────────────────────────

    @staticmethod
    def _compute_sma(values: list[float], period: int) -> list[float]:
        """Compute Simple Moving Average."""
        result = [0.0] * len(values)
        for i in range(period - 1, len(values)):
            result[i] = sum(values[i - period + 1 : i + 1]) / period
        return result

    @staticmethod
    def _compute_ema(values: list[float], period: int) -> list[float]:
        """Compute Exponential Moving Average."""
        result = [0.0] * len(values)
        if len(values) < period:
            return result
        multiplier = 2.0 / (period + 1)
        # Seed with SMA
        result[period - 1] = sum(values[:period]) / period
        for i in range(period, len(values)):
            result[i] = (values[i] - result[i - 1]) * multiplier + result[i - 1]
        return result

    @staticmethod
    def _compute_rsi(closes: list[float], period: int = 14) -> list[float]:
        """Compute RSI (Relative Strength Index)."""
        if len(closes) < period + 1:
            return [50.0] * len(closes)

        result = [50.0] * len(closes)
        gains = []
        losses = []

        for i in range(1, len(closes)):
            change = closes[i] - closes[i - 1]
            gains.append(max(0, change))
            losses.append(max(0, -change))

        if len(gains) < period:
            return result

        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        for i in range(period, len(gains)):
            if avg_loss == 0:
                result[i + 1] = 100.0
            else:
                rs = avg_gain / avg_loss
                result[i + 1] = 100.0 - (100.0 / (1.0 + rs))

            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        # Fill the period-th index
        if avg_loss == 0:
            result[period] = 100.0
        else:
            rs = sum(gains[:period]) / max(sum(losses[:period]), 1e-10)
            result[period] = 100.0 - (100.0 / (1.0 + rs))

        return result

    @staticmethod
    def _compute_macd(
        closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9
    ) -> tuple[list[float], list[float], list[float]]:
        """Compute MACD line, signal line, and histogram."""
        if len(closes) < slow + signal:
            return [], [], []

        # EMA helper
        def ema(values, period):
            result = [0.0] * len(values)
            if len(values) < period:
                return result
            mult = 2.0 / (period + 1)
            result[period - 1] = sum(values[:period]) / period
            for i in range(period, len(values)):
                result[i] = (values[i] - result[i - 1]) * mult + result[i - 1]
            return result

        ema_fast = ema(closes, fast)
        ema_slow = ema(closes, slow)

        macd_line = [0.0] * len(closes)
        for i in range(slow - 1, len(closes)):
            macd_line[i] = ema_fast[i] - ema_slow[i]

        # Signal line: EMA of MACD from index slow-1 onwards
        macd_subset = macd_line[slow - 1 :]
        signal_ema = ema(macd_subset, signal)

        signal_line = [0.0] * len(closes)
        for i in range(len(signal_ema)):
            signal_line[slow - 1 + i] = signal_ema[i]

        histogram = [0.0] * len(closes)
        for i in range(slow + signal - 2, len(closes)):
            histogram[i] = macd_line[i] - signal_line[i]

        return macd_line, signal_line, histogram


# ── Trading Query Handler ────────────────────────────────────────────────────


@dataclass
class TradeDetail:
    """Structured trade detail result. (Req 19.1)"""

    trade_id: str
    symbol: str
    strategy: str
    entry_price: float
    exit_price: Optional[float]
    quantity: int
    realized_pnl: Optional[float]
    entry_time: str
    exit_time: Optional[str]
    holding_period: Optional[str] = None


@dataclass
class PerformanceSummary:
    """Aggregated performance metrics for a time period. (Req 19.2)"""

    total_pnl: float
    trade_count: int
    win_count: int
    loss_count: int
    win_rate: float
    avg_profit: float
    best_trade_pnl: float
    best_trade_symbol: str
    worst_trade_pnl: float
    worst_trade_symbol: str
    sharpe_ratio: Optional[float]


@dataclass
class SignalExplanation:
    """Explanation of why a trade was taken. (Req 19.3)"""

    symbol: str
    signal_type: str
    strategy: str
    indicator_values: dict
    bias_state: str
    signal_time: str


@dataclass
class StockInfo:
    """Aggregated stock info for a symbol. (Req 19.4)"""

    symbol: str
    recent_sentiment: list[dict]
    bias_status: Optional[str]
    open_positions: list[dict]
    recent_trades: list[dict]


class TradingQueryHandler:
    """Handles structured trading data queries for the chatbot.

    Provides methods for:
    - Trade detail queries (Req 19.1)
    - Performance queries with time ranges (Req 19.2)
    - Signal explanation queries (Req 19.3)
    - Stock info queries (Req 19.4)
    - Time-range parsing (Req 19.6)

    All queries are scoped to the authenticated user's data only.
    """

    def __init__(self, db_pool=None):
        self.db_pool = db_pool

    # ── Time-range parsing (Req 19.6) ────────────────────────────────────

    @staticmethod
    def parse_time_range(
        query: str, now: Optional[datetime] = None
    ) -> tuple[Optional[datetime], Optional[datetime]]:
        """Parse natural-language time ranges from a query string.

        Supports: "last week", "last month", "last N days", "today",
        "yesterday", "this week", "this month", "this year",
        "from January", "from <month>", "last year".

        Returns (start, end) datetimes. Either may be None if not parseable.
        """
        now = now or datetime.now(timezone.utc)
        lower = query.lower()

        # "today"
        if "today" in lower:
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            return start, now

        # "yesterday"
        if "yesterday" in lower:
            yesterday = now - timedelta(days=1)
            start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
            end = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)
            return start, end

        # "last N days/weeks/months"
        match = re.search(r"last\s+(\d+)\s+(day|week|month)s?", lower)
        if match:
            n = int(match.group(1))
            unit = match.group(2)
            if unit == "day":
                start = now - timedelta(days=n)
            elif unit == "week":
                start = now - timedelta(weeks=n)
            elif unit == "month":
                start = now - timedelta(days=n * 30)
            return start, now

        # "last week" (no number)
        if "last week" in lower:
            start = now - timedelta(weeks=1)
            return start, now

        # "last month" (no number)
        if "last month" in lower:
            start = now - timedelta(days=30)
            return start, now

        # "last year"
        if "last year" in lower:
            start = now - timedelta(days=365)
            return start, now

        # "this week"
        if "this week" in lower:
            start = now - timedelta(days=now.weekday())
            start = start.replace(hour=0, minute=0, second=0, microsecond=0)
            return start, now

        # "this month"
        if "this month" in lower:
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            return start, now

        # "this year"
        if "this year" in lower:
            start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            return start, now

        # "from January", "from February", etc.
        months = {
            "january": 1,
            "february": 2,
            "march": 3,
            "april": 4,
            "may": 5,
            "june": 6,
            "july": 7,
            "august": 8,
            "september": 9,
            "october": 10,
            "november": 11,
            "december": 12,
        }
        match = re.search(r"from\s+(" + "|".join(months.keys()) + r")", lower)
        if match:
            month_num = months[match.group(1)]
            year = now.year if month_num <= now.month else now.year - 1
            start = datetime(year, month_num, 1, tzinfo=timezone.utc)
            return start, now

        return None, None

    # ── Trade detail queries (Req 19.1) ──────────────────────────────────

    async def get_trade_details(self, user_id: str, trade_id: str) -> Optional[TradeDetail]:
        """Retrieve details for a specific trade by trade_id."""
        if not self.db_pool:
            return None
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT id, symbol, strategy, entry_price, exit_price,
                           quantity, realized_pnl, entry_time, exit_time
                    FROM trades
                    WHERE user_id = $1 AND (id::text = $2 OR trade_id = $2)
                    """,
                    user_id,
                    trade_id,
                )
                if not row:
                    return None
                return self._row_to_trade_detail(dict(row))
        except Exception as exc:
            logger.error("get_trade_details failed for user %s: %s", user_id, exc)
            return None

    async def get_trades_by_symbol(
        self,
        user_id: str,
        symbol: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> list[TradeDetail]:
        """Retrieve trades for a specific symbol, optionally filtered by time range."""
        if not self.db_pool:
            return []
        try:
            async with self.db_pool.acquire() as conn:
                query = """
                    SELECT id, symbol, strategy, entry_price, exit_price,
                           quantity, realized_pnl, entry_time, exit_time
                    FROM trades
                    WHERE user_id = $1 AND symbol = $2
                """
                params: list[Any] = [user_id, symbol]
                if start:
                    query += f" AND entry_time >= ${len(params) + 1}"
                    params.append(start)
                if end:
                    query += f" AND entry_time <= ${len(params) + 1}"
                    params.append(end)
                query += " ORDER BY entry_time DESC LIMIT 50"
                rows = await conn.fetch(query, *params)
                return [self._row_to_trade_detail(dict(r)) for r in rows]
        except Exception as exc:
            logger.error("get_trades_by_symbol failed for user %s: %s", user_id, exc)
            return []

    @staticmethod
    def _row_to_trade_detail(row: dict) -> TradeDetail:
        """Convert a DB row dict to a TradeDetail dataclass."""
        holding_period = None
        entry_time = row.get("entry_time")
        exit_time = row.get("exit_time")
        if entry_time and exit_time:
            try:
                if isinstance(entry_time, str):
                    et = datetime.fromisoformat(entry_time)
                else:
                    et = entry_time
                if isinstance(exit_time, str):
                    xt = datetime.fromisoformat(exit_time)
                else:
                    xt = exit_time
                delta = xt - et
                total_seconds = int(delta.total_seconds())
                days = total_seconds // 86400
                hours = (total_seconds % 86400) // 3600
                minutes = (total_seconds % 3600) // 60
                parts = []
                if days:
                    parts.append(f"{days}d")
                if hours:
                    parts.append(f"{hours}h")
                if minutes or not parts:
                    parts.append(f"{minutes}m")
                holding_period = " ".join(parts)
            except (ValueError, TypeError):
                pass

        return TradeDetail(
            trade_id=str(row.get("id", "")),
            symbol=row.get("symbol", ""),
            strategy=row.get("strategy", ""),
            entry_price=float(row.get("entry_price", 0)),
            exit_price=float(row["exit_price"]) if row.get("exit_price") is not None else None,
            quantity=int(row.get("quantity", 0)),
            realized_pnl=(
                float(row["realized_pnl"]) if row.get("realized_pnl") is not None else None
            ),
            entry_time=str(row.get("entry_time", "")),
            exit_time=str(row.get("exit_time", "")) if row.get("exit_time") else None,
            holding_period=holding_period,
        )

    # ── Performance queries (Req 19.2) ───────────────────────────────────

    async def get_performance_summary(
        self, user_id: str, start: Optional[datetime] = None, end: Optional[datetime] = None
    ) -> Optional[PerformanceSummary]:
        """Calculate performance metrics for the user's trades in a time range."""
        if not self.db_pool:
            return None
        try:
            async with self.db_pool.acquire() as conn:
                query = """
                    SELECT symbol, realized_pnl
                    FROM trades
                    WHERE user_id = $1 AND realized_pnl IS NOT NULL
                """
                params: list[Any] = [user_id]
                if start:
                    query += f" AND entry_time >= ${len(params) + 1}"
                    params.append(start)
                if end:
                    query += f" AND entry_time <= ${len(params) + 1}"
                    params.append(end)
                query += " ORDER BY entry_time DESC"
                rows = await conn.fetch(query, *params)

                if not rows:
                    return None

                return self._compute_performance(rows)
        except Exception as exc:
            logger.error("get_performance_summary failed for user %s: %s", user_id, exc)
            return None

    @staticmethod
    def _compute_performance(rows: list) -> PerformanceSummary:
        """Compute performance metrics from trade rows."""
        pnls = []
        symbols = []
        for r in rows:
            pnl = float(r["realized_pnl"])
            pnls.append(pnl)
            symbols.append(r["symbol"])

        total_pnl = sum(pnls)
        trade_count = len(pnls)
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        win_count = len(wins)
        loss_count = len(losses)
        win_rate = (win_count / trade_count * 100) if trade_count > 0 else 0.0
        avg_profit = total_pnl / trade_count if trade_count > 0 else 0.0

        best_idx = pnls.index(max(pnls))
        worst_idx = pnls.index(min(pnls))

        # Sharpe ratio: mean(pnl) / std(pnl) — annualized assuming ~252 trading days
        sharpe = None
        if trade_count >= 2:
            mean_pnl = total_pnl / trade_count
            variance = sum((p - mean_pnl) ** 2 for p in pnls) / (trade_count - 1)
            std_pnl = math.sqrt(variance)
            if std_pnl > 0:
                sharpe = round((mean_pnl / std_pnl) * math.sqrt(252), 2)

        return PerformanceSummary(
            total_pnl=round(total_pnl, 2),
            trade_count=trade_count,
            win_count=win_count,
            loss_count=loss_count,
            win_rate=round(win_rate, 2),
            avg_profit=round(avg_profit, 2),
            best_trade_pnl=round(pnls[best_idx], 2),
            best_trade_symbol=symbols[best_idx],
            worst_trade_pnl=round(pnls[worst_idx], 2),
            worst_trade_symbol=symbols[worst_idx],
            sharpe_ratio=sharpe,
        )

    # ── Signal explanation (Req 19.3) ────────────────────────────────────

    async def get_signal_explanation(
        self, user_id: str, symbol: str, trade_entry_time: Optional[str] = None
    ) -> Optional[SignalExplanation]:
        """Explain why a trade was taken: strategy conditions, indicator values, bias state."""
        if not self.db_pool:
            return None
        try:
            async with self.db_pool.acquire() as conn:
                query = """
                    SELECT symbol, signal_type, strategy, indicator_values,
                           bias_state, created_at
                    FROM signals
                    WHERE user_id = $1 AND symbol = $2
                """
                params: list[Any] = [user_id, symbol]
                if trade_entry_time:
                    # Find the signal closest to (but before) the trade entry time
                    query += f" AND created_at <= ${len(params) + 1}"
                    params.append(trade_entry_time)
                query += " ORDER BY created_at DESC LIMIT 1"
                row = await conn.fetchrow(query, *params)
                if not row:
                    return None

                indicator_values = row["indicator_values"]
                if isinstance(indicator_values, str):
                    try:
                        indicator_values = json.loads(indicator_values)
                    except (json.JSONDecodeError, TypeError):
                        indicator_values = {}
                elif not isinstance(indicator_values, dict):
                    indicator_values = {}

                return SignalExplanation(
                    symbol=row["symbol"],
                    signal_type=row["signal_type"],
                    strategy=row["strategy"],
                    indicator_values=indicator_values,
                    bias_state=row["bias_state"] or "UNKNOWN",
                    signal_time=str(row["created_at"]),
                )
        except Exception as exc:
            logger.error("get_signal_explanation failed for user %s: %s", user_id, exc)
            return None

    # ── Stock queries (Req 19.4) ─────────────────────────────────────────

    async def get_stock_info(self, user_id: str, symbol: str) -> Optional[StockInfo]:
        """Retrieve stock info: sentiment, bias, open positions, recent trades."""
        if not self.db_pool:
            return None
        try:
            async with self.db_pool.acquire() as conn:
                # Recent sentiment
                sentiment_rows = await conn.fetch(
                    """
                    SELECT ticker, sentiment, score, headline, created_at
                    FROM sentiment_log
                    WHERE user_id = $1 AND ticker = $2
                    ORDER BY created_at DESC LIMIT 5
                    """,
                    user_id,
                    symbol,
                )

                # Latest bias
                bias_row = await conn.fetchrow(
                    """
                    SELECT bias FROM bias_log
                    WHERE user_id = $1 AND ticker = $2
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    user_id,
                    symbol,
                )

                # Open positions (trades without exit)
                open_rows = await conn.fetch(
                    """
                    SELECT id, symbol, strategy, entry_price, quantity, entry_time
                    FROM trades
                    WHERE user_id = $1 AND symbol = $2 AND exit_time IS NULL
                    ORDER BY entry_time DESC
                    """,
                    user_id,
                    symbol,
                )

                # Recent closed trades
                trade_rows = await conn.fetch(
                    """
                    SELECT id, symbol, strategy, entry_price, exit_price,
                           realized_pnl, entry_time, exit_time
                    FROM trades
                    WHERE user_id = $1 AND symbol = $2 AND exit_time IS NOT NULL
                    ORDER BY exit_time DESC LIMIT 5
                    """,
                    user_id,
                    symbol,
                )

                return StockInfo(
                    symbol=symbol,
                    recent_sentiment=[dict(r) for r in sentiment_rows],
                    bias_status=bias_row["bias"] if bias_row else None,
                    open_positions=[dict(r) for r in open_rows],
                    recent_trades=[dict(r) for r in trade_rows],
                )
        except Exception as exc:
            logger.error("get_stock_info failed for user %s: %s", user_id, exc)
            return None


# ── Chatbot Service ──────────────────────────────────────────────────────────


class ChatbotService:
    """Gen AI chatbot with RAG over user trading data.

    Orchestrates: conversation management (Redis), RAG retrieval (PostgreSQL),
    LLM completion, and optional chart generation.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        db_pool=None,
        redis=None,
        chart_gen: Optional[ChartGenerator] = None,
    ):
        self.llm = llm_client
        self.db_pool = db_pool
        self.redis = redis
        self.chart_gen = chart_gen or ChartGenerator()

    # ── Public API ───────────────────────────────────────────────────────

    async def chat(self, user_id: str, message: str) -> ChatResponse:
        """Process a user message: RAG retrieval → LLM → response.

        Only accesses the authenticated user's own data.
        Supports English and Hinglish input.
        """
        if not user_id or not message or not message.strip():
            return ChatResponse(text="Please provide a message.", response_time_ms=0)

        start = time.monotonic()

        # 1. Load conversation history from Redis
        history = await self._load_conversation(user_id)

        # 2. RAG: retrieve relevant context from user's data
        context = await self._retrieve_context(user_id, message.strip())

        # 3. Build messages for LLM
        llm_messages = self._build_llm_messages(history, message.strip(), context)

        # 4. Call LLM
        assistant_text = await self.llm.complete(llm_messages)

        # 5. If no data was found and LLM didn't have context, be explicit
        if not context.has_data and self._is_data_query(message):
            assistant_text = NO_DATA_RESPONSE

        elapsed_ms = int((time.monotonic() - start) * 1000)

        # 6. Save updated conversation to Redis
        user_msg = Message(role=MessageRole.USER, content=message.strip())
        assistant_msg = Message(role=MessageRole.ASSISTANT, content=assistant_text)
        history.append(user_msg)
        history.append(assistant_msg)
        await self._save_conversation(user_id, history)

        return ChatResponse(
            text=assistant_text,
            sources=self._extract_sources(context),
            response_time_ms=elapsed_ms,
        )

    async def get_history(self, user_id: str) -> list[dict]:
        """Get conversation history for the user."""
        history = await self._load_conversation(user_id)
        return [m.to_dict() for m in history]

    async def clear_session(self, user_id: str) -> bool:
        """Clear the user's conversation session."""
        if self.redis is None:
            return False
        try:
            key = f"{REDIS_CHAT_KEY_PREFIX}{user_id}"
            await self.redis.delete(key)
            return True
        except Exception as exc:
            logger.error("Failed to clear chat session for %s: %s", user_id, exc)
            return False

    # ── Conversation persistence (Redis) ─────────────────────────────────

    async def _load_conversation(self, user_id: str) -> list[Message]:
        """Load conversation history from Redis."""
        if self.redis is None:
            return []
        try:
            key = f"{REDIS_CHAT_KEY_PREFIX}{user_id}"
            raw = await self.redis.get(key)
            if not raw:
                return []
            data = json.loads(raw)
            if not isinstance(data, list):
                return []
            return [Message.from_dict(m) for m in data]
        except Exception as exc:
            logger.error("Failed to load chat history for %s: %s", user_id, exc)
            return []

    async def _save_conversation(self, user_id: str, messages: list[Message]) -> None:
        """Save conversation history to Redis with TTL.

        Enforces max 20 exchanges (40 messages: 20 user + 20 assistant).
        """
        if self.redis is None:
            return
        try:
            # Trim to max exchanges (each exchange = 1 user + 1 assistant msg)
            max_messages = MAX_CONVERSATION_EXCHANGES * 2
            if len(messages) > max_messages:
                messages = messages[-max_messages:]

            key = f"{REDIS_CHAT_KEY_PREFIX}{user_id}"
            payload = json.dumps([m.to_dict() for m in messages])
            await self.redis.set(key, payload, ex=REDIS_CHAT_TTL_SECONDS)
        except Exception as exc:
            logger.error("Failed to save chat history for %s: %s", user_id, exc)

    # ── RAG retrieval ────────────────────────────────────────────────────

    async def _retrieve_context(self, user_id: str, query: str) -> RAGContext:
        """Query user's trades, sentiment logs, signal history from PostgreSQL.

        Only accesses the authenticated user's own data (user_id filter).
        """
        context = RAGContext()

        if self.db_pool is None:
            return context

        try:
            async with self.db_pool.acquire() as conn:
                # Retrieve recent trades for the user
                trade_rows = await conn.fetch(
                    """
                    SELECT id, symbol, strategy, entry_price, exit_price,
                           quantity, realized_pnl, entry_time, exit_time
                    FROM trades
                    WHERE user_id = $1
                    ORDER BY entry_time DESC
                    LIMIT 50
                    """,
                    user_id,
                )
                context.trades = [dict(r) for r in trade_rows]

                # Retrieve recent sentiment logs
                sentiment_rows = await conn.fetch(
                    """
                    SELECT ticker, sentiment, score, headline, created_at
                    FROM sentiment_log
                    WHERE user_id = $1
                    ORDER BY created_at DESC
                    LIMIT 20
                    """,
                    user_id,
                )
                context.sentiment_logs = [dict(r) for r in sentiment_rows]

                # Retrieve recent signal history
                signal_rows = await conn.fetch(
                    """
                    SELECT symbol, signal_type, strategy, indicator_values,
                           bias_state, created_at
                    FROM signals
                    WHERE user_id = $1
                    ORDER BY created_at DESC
                    LIMIT 20
                    """,
                    user_id,
                )
                context.signals = [dict(r) for r in signal_rows]

        except Exception as exc:
            logger.error("RAG retrieval failed for user %s: %s", user_id, exc)

        return context

    # ── LLM message building ─────────────────────────────────────────────

    def _build_llm_messages(
        self,
        history: list[Message],
        user_message: str,
        context: RAGContext,
    ) -> list[Message]:
        """Build the full message list for the LLM call.

        Includes: system prompt, RAG context, conversation history, new user message.
        """
        messages: list[Message] = []

        # System prompt
        messages.append(Message(role=MessageRole.SYSTEM, content=SYSTEM_PROMPT))

        # RAG context as a system message
        if context.has_data:
            context_str = context.to_context_string()
            messages.append(
                Message(
                    role=MessageRole.SYSTEM,
                    content=f"User's trading data context:\n{context_str}",
                )
            )

        # Conversation history (skip system messages from history)
        for msg in history:
            if msg.role in (MessageRole.USER, MessageRole.ASSISTANT):
                messages.append(msg)

        # New user message
        messages.append(Message(role=MessageRole.USER, content=user_message))

        return messages

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _is_data_query(message: str) -> bool:
        """Heuristic: does the message ask about trading data?"""
        data_keywords = [
            "trade",
            "trades",
            "position",
            "positions",
            "pnl",
            "p&l",
            "profit",
            "loss",
            "performance",
            "win rate",
            "sharpe",
            "portfolio",
            "holding",
            "stock",
            "signal",
            "sentiment",
            "strategy",
            "entry",
            "exit",
            "buy",
            "sell",
            # Hinglish keywords
            "kitna",
            "kamai",
            "nuksan",
            "kharida",
            "becha",
        ]
        lower = message.lower()
        return any(kw in lower for kw in data_keywords)

    @staticmethod
    def _extract_sources(context: RAGContext) -> list[str]:
        """Extract source references from RAG context."""
        sources = []
        if context.trades:
            sources.append(f"trades ({len(context.trades)} records)")
        if context.sentiment_logs:
            sources.append(f"sentiment_logs ({len(context.sentiment_logs)} records)")
        if context.signals:
            sources.append(f"signals ({len(context.signals)} records)")
        return sources

    # ── Serialization & Validation (Req 21.1, 21.2, 21.4, 21.5) ────────

    @staticmethod
    def serialize_query_results(results) -> str:
        """Serialize trade query results to JSON for LLM context.

        Handles dataclass instances (TradeDetail, PerformanceSummary,
        SignalExplanation, StockInfo), plain dicts, and lists thereof.
        Requirement 21.1.
        """
        from dataclasses import asdict, is_dataclass

        def _convert(obj):
            if is_dataclass(obj) and not isinstance(obj, type):
                return asdict(obj)
            if isinstance(obj, list):
                return [_convert(item) for item in obj]
            if isinstance(obj, dict):
                return {k: _convert(v) for k, v in obj.items()}
            return obj

        converted = _convert(results)
        return json.dumps(converted, default=str)

    @staticmethod
    def deserialize_llm_response(response_json: str, expected_type: type = dict) -> Any:
        """Deserialize LLM structured response back to typed objects.

        Supports: TradeDetail, PerformanceSummary, SignalExplanation,
        StockInfo, dict, and list[dict].  Returns None on parse failure.
        Requirement 21.2.
        """
        try:
            data = json.loads(response_json)
        except (json.JSONDecodeError, TypeError):
            return None

        type_map = {
            TradeDetail: TradeDetail,
            PerformanceSummary: PerformanceSummary,
            SignalExplanation: SignalExplanation,
            StockInfo: StockInfo,
        }

        if expected_type in type_map:
            cls = type_map[expected_type]
            try:
                if isinstance(data, list):
                    return [cls(**item) for item in data]
                if isinstance(data, dict):
                    return cls(**data)
            except (TypeError, KeyError):
                return None

        return data

    @staticmethod
    def validate_numeric_accuracy(
        llm_values: dict, db_values: dict, tolerance: float = 0.01
    ) -> bool:
        """Validate LLM response numeric values match DB within tolerance.

        Returns True if all numeric values match within tolerance, False otherwise.
        Requirement 21.4.
        """
        for key, llm_val in llm_values.items():
            if key not in db_values:
                continue
            db_val = db_values[key]
            try:
                llm_f = float(llm_val)
                db_f = float(db_val)
            except (ValueError, TypeError):
                continue
            if abs(llm_f - db_f) > tolerance:
                return False
        return True

    @staticmethod
    def validate_numeric_accuracy_detailed(
        llm_values: dict, db_values: dict, tolerance: float = 0.01
    ) -> list[dict]:
        """Validate LLM response numeric values match DB within tolerance.

        Returns a list of discrepancy dicts. An empty list means all values
        are accurate.  Each discrepancy contains: key, llm_value, db_value,
        difference.
        Requirement 21.4.
        """
        discrepancies: list[dict] = []
        for key, llm_val in llm_values.items():
            if key not in db_values:
                continue
            db_val = db_values[key]
            try:
                llm_f = float(llm_val)
                db_f = float(db_val)
            except (ValueError, TypeError):
                continue
            diff = abs(llm_f - db_f)
            if diff > tolerance:
                discrepancies.append(
                    {
                        "key": key,
                        "llm_value": llm_f,
                        "db_value": db_f,
                        "difference": round(diff, 6),
                    }
                )
        return discrepancies

    @staticmethod
    def validate_trade_ids(trade_ids: list[str], user_trade_ids: list[str]) -> list[str]:
        """Verify all trade IDs referenced in LLM responses exist in user's history.

        Returns a list of invalid trade IDs (those not found in user_trade_ids).
        An empty list means all IDs are valid.
        Requirement 21.5.
        """
        valid_set = set(str(tid) for tid in user_trade_ids)
        return [str(tid) for tid in trade_ids if str(tid) not in valid_set]
