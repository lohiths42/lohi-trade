"""Backtesting engine for LOHI-TRADE system.

Provides vectorized backtesting for Mean Reversion, Trend Following,
and Opening Range Breakout strategies with realistic Indian market
transaction costs, slippage, and performance metrics.

Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 15.6, 15.7, 15.8
"""

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from src.utils.logger import get_logger

logger = get_logger("BacktestingEngine")


# ---------------------------------------------------------------------------
# Indian market transaction cost constants
# ---------------------------------------------------------------------------
STT_RATE = 0.00025  # 0.025% on sell side
EXCHANGE_CHARGE_RATE = 0.0000345  # 0.00345% on both sides
GST_RATE = 0.18  # 18% on (brokerage + exchange charges)
STAMP_DUTY_RATE = 0.00003  # 0.003% on buy side
BROKERAGE_PER_ORDER = 20.0  # ₹20 flat fee per order
SLIPPAGE_PCT = 0.0005  # 0.05%

# Minimum performance thresholds
MIN_SHARPE = 1.5
MIN_WIN_RATE = 45.0
MAX_DRAWDOWN = 5.0
MIN_PROFIT_FACTOR = 1.5

RISK_FREE_RATE = 0.065  # ~6.5% Indian 10-year bond yield
TRADING_DAYS = 252


@dataclass
class TradeRecord:
    """Single trade entry/exit record."""

    symbol: str
    strategy: str
    side: str  # BUY or SELL
    entry_price: float
    exit_price: float
    quantity: int
    entry_date: Any  # date or Timestamp
    exit_date: Any
    gross_pnl: float = 0.0
    transaction_costs: float = 0.0
    net_pnl: float = 0.0
    holding_period: int = 0  # in bars / days


@dataclass
class BacktestResult:
    """Container for a single strategy backtest output."""

    strategy_name: str
    metrics: dict[str, float] = field(default_factory=dict)
    equity_curve: pd.Series | None = None
    trades: list[TradeRecord] = field(default_factory=list)
    trade_log: pd.DataFrame | None = None
    passed_thresholds: bool = False


class BacktestingEngine:
    """Vectorized backtesting engine for LOHI-TRADE strategies.

    Uses pandas/numpy for core calculations. If vectorbt is installed it
    can be leveraged, but the engine works without it.
    """

    STRATEGIES = ["mean_reversion", "trend_following", "orb"]

    def __init__(self, config: Any, data_manager: Any = None):
        """Args:
        config: Application configuration object.
        data_manager: Optional HistoricalDataManager for loading data.

        """
        self.config = config
        self.data_manager = data_manager

    # ------------------------------------------------------------------
    # Transaction costs
    # ------------------------------------------------------------------

    def apply_transaction_costs(self, trades: list[TradeRecord]) -> list[TradeRecord]:
        """Apply realistic Indian market transaction costs to each trade.

        Costs applied:
        - STT: 0.025% on sell-side turnover
        - Exchange charges: 0.00345% on both sides
        - GST: 18% on (brokerage + exchange charges)
        - Stamp duty: 0.003% on buy-side turnover
        - Brokerage: ₹20 per order (entry + exit = ₹40)

        Returns:
            The same list with transaction_costs and net_pnl updated.

        """
        for t in trades:
            buy_turnover = t.entry_price * t.quantity
            sell_turnover = t.exit_price * t.quantity

            stt = sell_turnover * STT_RATE
            exchange = (buy_turnover + sell_turnover) * EXCHANGE_CHARGE_RATE
            brokerage = BROKERAGE_PER_ORDER * 2  # entry + exit
            gst = (brokerage + exchange) * GST_RATE
            stamp = buy_turnover * STAMP_DUTY_RATE

            total_cost = stt + exchange + gst + stamp + brokerage
            t.transaction_costs = total_cost
            t.gross_pnl = (
                (t.exit_price - t.entry_price) * t.quantity
                if t.side == "BUY"
                else (t.entry_price - t.exit_price) * t.quantity
            )
            t.net_pnl = t.gross_pnl - total_cost

        return trades

    # ------------------------------------------------------------------
    # Slippage
    # ------------------------------------------------------------------

    @staticmethod
    def apply_slippage(price: float, side: str) -> float:
        """Apply 0.05% slippage to an execution price.

        For BUY orders the price worsens (increases).
        For SELL orders the price worsens (decreases).

        Args:
            price: Intended execution price.
            side: 'BUY' or 'SELL'.

        Returns:
            Adjusted price after slippage.

        """
        if side == "BUY":
            return price * (1 + SLIPPAGE_PCT)
        return price * (1 - SLIPPAGE_PCT)

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def calculate_metrics(
        self,
        equity_curve: pd.Series,
        trades: list[TradeRecord],
    ) -> dict[str, float]:
        """Calculate performance metrics from an equity curve and trade list.

        Metrics:
        - sharpe_ratio: annualised (mean - Rf) / std * sqrt(252)
        - max_drawdown: maximum peak-to-trough decline (%)
        - win_rate: percentage of winning trades
        - profit_factor: gross_profit / gross_loss
        - total_return: percentage return on initial capital

        Args:
            equity_curve: Series of portfolio values indexed by date/bar.
            trades: List of TradeRecord objects.

        Returns:
            Dict with metric names as keys.

        """
        metrics: dict[str, float] = {}

        # --- Returns ---
        if len(equity_curve) < 2:
            return {
                "sharpe_ratio": 0.0,
                "max_drawdown": 0.0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "total_return": 0.0,
            }

        returns = equity_curve.pct_change().dropna()
        daily_rf = RISK_FREE_RATE / TRADING_DAYS

        # Sharpe Ratio
        if returns.std() == 0:
            metrics["sharpe_ratio"] = 0.0
        else:
            excess = returns.mean() - daily_rf
            metrics["sharpe_ratio"] = (excess / returns.std()) * np.sqrt(TRADING_DAYS)

        # Max Drawdown
        cummax = equity_curve.cummax()
        drawdown = (equity_curve - cummax) / cummax * 100  # as percentage
        metrics["max_drawdown"] = abs(drawdown.min())

        # Total Return
        initial = equity_curve.iloc[0]
        final = equity_curve.iloc[-1]
        metrics["total_return"] = ((final - initial) / initial) * 100 if initial != 0 else 0.0

        # Win Rate & Profit Factor
        if not trades:
            metrics["win_rate"] = 0.0
            metrics["profit_factor"] = 0.0
        else:
            wins = [t for t in trades if t.net_pnl > 0]
            losses = [t for t in trades if t.net_pnl <= 0]
            metrics["win_rate"] = (len(wins) / len(trades)) * 100

            gross_profit = sum(t.net_pnl for t in wins) if wins else 0.0
            gross_loss = abs(sum(t.net_pnl for t in losses)) if losses else 0.0
            metrics["profit_factor"] = (
                (gross_profit / gross_loss) if gross_loss > 0 else float("inf")
            )

        return metrics

    # ------------------------------------------------------------------
    # Trade log
    # ------------------------------------------------------------------

    def generate_trade_log(self, trades: list[TradeRecord]) -> pd.DataFrame:
        """Convert trade records into a DataFrame log.

        Columns: symbol, strategy, side, entry_price, exit_price, quantity,
                 entry_date, exit_date, gross_pnl, transaction_costs,
                 net_pnl, holding_period
        """
        if not trades:
            return pd.DataFrame(
                columns=[
                    "symbol",
                    "strategy",
                    "side",
                    "entry_price",
                    "exit_price",
                    "quantity",
                    "entry_date",
                    "exit_date",
                    "gross_pnl",
                    "transaction_costs",
                    "net_pnl",
                    "holding_period",
                ]
            )

        rows = []
        for t in trades:
            rows.append(
                {
                    "symbol": t.symbol,
                    "strategy": t.strategy,
                    "side": t.side,
                    "entry_price": t.entry_price,
                    "exit_price": t.exit_price,
                    "quantity": t.quantity,
                    "entry_date": t.entry_date,
                    "exit_date": t.exit_date,
                    "gross_pnl": t.gross_pnl,
                    "transaction_costs": t.transaction_costs,
                    "net_pnl": t.net_pnl,
                    "holding_period": t.holding_period,
                }
            )
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------
    # Threshold validation
    # ------------------------------------------------------------------

    def validate_thresholds(self, metrics: dict[str, float]) -> dict[str, Any]:
        """Check whether metrics meet minimum performance thresholds.

        Thresholds:
        - Sharpe Ratio > 1.5
        - Max Drawdown < 5%
        - Win Rate > 45%
        - Profit Factor > 1.5

        Returns:
            Dict with 'passed' bool and per-check results.

        """
        checks = {
            "sharpe_ratio": metrics.get("sharpe_ratio", 0) > MIN_SHARPE,
            "max_drawdown": metrics.get("max_drawdown", 100) < MAX_DRAWDOWN,
            "win_rate": metrics.get("win_rate", 0) > MIN_WIN_RATE,
            "profit_factor": metrics.get("profit_factor", 0) > MIN_PROFIT_FACTOR,
        }
        return {
            "passed": all(checks.values()),
            "checks": checks,
            "thresholds": {
                "sharpe_ratio": f"> {MIN_SHARPE}",
                "max_drawdown": f"< {MAX_DRAWDOWN}%",
                "win_rate": f"> {MIN_WIN_RATE}%",
                "profit_factor": f"> {MIN_PROFIT_FACTOR}",
            },
        }

    # ------------------------------------------------------------------
    # Strategy simulation helpers
    # ------------------------------------------------------------------

    def _simulate_mean_reversion(
        self,
        data: pd.DataFrame,
        initial_capital: float,
    ) -> BacktestResult:
        """Simulate mean reversion strategy on OHLCV data."""
        return self._simulate_generic(data, initial_capital, "mean_reversion")

    def _simulate_trend_following(
        self,
        data: pd.DataFrame,
        initial_capital: float,
    ) -> BacktestResult:
        """Simulate trend following strategy on OHLCV data."""
        return self._simulate_generic(data, initial_capital, "trend_following")

    def _simulate_orb(
        self,
        data: pd.DataFrame,
        initial_capital: float,
    ) -> BacktestResult:
        """Simulate opening range breakout strategy on OHLCV data."""
        return self._simulate_generic(data, initial_capital, "orb")

    def _simulate_generic(
        self,
        data: pd.DataFrame,
        initial_capital: float,
        strategy_name: str,
    ) -> BacktestResult:
        """Generic vectorized simulation using simple signal columns.

        Expects *data* to contain at least: close, and optionally
        'signal' column with 1 (buy) / -1 (sell) / 0 (hold).
        If no signal column, generates signals based on strategy rules.
        """
        df = data.copy()
        if df.empty:
            return BacktestResult(strategy_name=strategy_name)

        # Ensure we have a close column
        if "close" not in df.columns:
            return BacktestResult(strategy_name=strategy_name)

        # Generate signals if not provided
        if "signal" not in df.columns:
            df["signal"] = self._generate_signals(df, strategy_name)

        trades: list[TradeRecord] = []
        equity = [initial_capital]
        cash = initial_capital
        position = 0
        entry_price = 0.0
        entry_idx = 0

        symbol = df["symbol"].iloc[0] if "symbol" in df.columns else "UNKNOWN"

        for i in range(len(df)):
            sig = df["signal"].iloc[i]
            close = df["close"].iloc[i]

            if sig == 1 and position == 0:
                # Open long
                adj_price = self.apply_slippage(close, "BUY")
                qty = max(1, int(cash * 0.1 / adj_price))  # 10% of capital
                if qty * adj_price <= cash:
                    position = qty
                    entry_price = adj_price
                    entry_idx = i
                    cash -= qty * adj_price

            elif sig == -1 and position > 0:
                # Close long
                adj_price = self.apply_slippage(close, "SELL")
                cash += position * adj_price

                dt_entry = df.index[entry_idx] if hasattr(df.index, "__getitem__") else entry_idx
                dt_exit = df.index[i] if hasattr(df.index, "__getitem__") else i

                trade = TradeRecord(
                    symbol=symbol,
                    strategy=strategy_name,
                    side="BUY",
                    entry_price=entry_price,
                    exit_price=adj_price,
                    quantity=position,
                    entry_date=dt_entry,
                    exit_date=dt_exit,
                    holding_period=i - entry_idx,
                )
                trades.append(trade)
                position = 0

            # Mark-to-market equity
            mtm = cash + position * close
            equity.append(mtm)

        # Close any remaining position at last close
        if position > 0:
            last_close = df["close"].iloc[-1]
            adj_price = self.apply_slippage(last_close, "SELL")
            cash += position * adj_price

            dt_entry = df.index[entry_idx] if hasattr(df.index, "__getitem__") else entry_idx
            dt_exit = df.index[-1] if hasattr(df.index, "__getitem__") else len(df) - 1

            trade = TradeRecord(
                symbol=symbol,
                strategy=strategy_name,
                side="BUY",
                entry_price=entry_price,
                exit_price=adj_price,
                quantity=position,
                entry_date=dt_entry,
                exit_date=dt_exit,
                holding_period=len(df) - 1 - entry_idx,
            )
            trades.append(trade)
            equity.append(cash)

        # Apply transaction costs
        trades = self.apply_transaction_costs(trades)

        # Rebuild equity accounting for costs
        total_costs = sum(t.transaction_costs for t in trades)
        equity_series = pd.Series(equity[: len(df) + 1])
        if len(equity_series) > 1:
            equity_series.iloc[-1] -= total_costs

        metrics = self.calculate_metrics(equity_series, trades)
        trade_log = self.generate_trade_log(trades)
        threshold_result = self.validate_thresholds(metrics)

        return BacktestResult(
            strategy_name=strategy_name,
            metrics=metrics,
            equity_curve=equity_series,
            trades=trades,
            trade_log=trade_log,
            passed_thresholds=threshold_result["passed"],
        )

    def _generate_signals(self, df: pd.DataFrame, strategy: str) -> pd.Series:
        """Generate simple trading signals based on strategy type.

        Returns Series of 1 (buy), -1 (sell), 0 (hold).
        """
        signals = pd.Series(0, index=df.index)

        if strategy == "mean_reversion":
            # Simple mean reversion: buy when close < SMA-2std, sell when close > SMA
            window = 20
            if len(df) < window:
                return signals
            sma = df["close"].rolling(window).mean()
            std = df["close"].rolling(window).std()
            lower = sma - 2 * std

            signals[df["close"] < lower] = 1
            signals[df["close"] > sma] = -1

        elif strategy == "trend_following":
            # Simple trend: buy on EMA crossover, sell on cross-under
            ema_fast = df["close"].ewm(span=9, adjust=False).mean()
            ema_slow = df["close"].ewm(span=21, adjust=False).mean()

            prev_fast = ema_fast.shift(1)
            prev_slow = ema_slow.shift(1)

            signals[(ema_fast > ema_slow) & (prev_fast <= prev_slow)] = 1
            signals[(ema_fast < ema_slow) & (prev_fast >= prev_slow)] = -1

        elif strategy == "orb":
            # Simplified ORB: buy on breakout above rolling high, sell on breakdown
            window = 15
            if len(df) < window:
                return signals
            rolling_high = (
                df["high"].rolling(window).max()
                if "high" in df.columns
                else df["close"].rolling(window).max()
            )
            rolling_low = (
                df["low"].rolling(window).min()
                if "low" in df.columns
                else df["close"].rolling(window).min()
            )

            signals[df["close"] > rolling_high.shift(1)] = 1
            signals[df["close"] < rolling_low.shift(1)] = -1

        return signals

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_backtest(
        self,
        strategy_name: str,
        data: pd.DataFrame,
        initial_capital: float = 500_000.0,
    ) -> BacktestResult:
        """Run a single strategy backtest.

        Args:
            strategy_name: One of 'mean_reversion', 'trend_following', 'orb'.
            data: OHLCV DataFrame with at least a 'close' column.
            initial_capital: Starting capital in INR.

        Returns:
            BacktestResult with metrics, equity curve, and trade log.

        """
        logger.info(
            f"Running backtest for {strategy_name}",
            extra={
                "initial_capital": initial_capital,
                "data_rows": len(data),
            },
        )

        dispatch = {
            "mean_reversion": self._simulate_mean_reversion,
            "trend_following": self._simulate_trend_following,
            "orb": self._simulate_orb,
        }

        simulator = dispatch.get(strategy_name)
        if simulator is None:
            logger.error(f"Unknown strategy: {strategy_name}")
            return BacktestResult(strategy_name=strategy_name)

        result = simulator(data, initial_capital)

        logger.info(
            f"Backtest complete for {strategy_name}",
            extra={"metrics": result.metrics, "num_trades": len(result.trades)},
        )
        return result

    def run_all_strategies(
        self,
        data: pd.DataFrame,
        initial_capital: float = 500_000.0,
    ) -> dict[str, BacktestResult]:
        """Run backtests for all three strategies and return combined results.

        Args:
            data: OHLCV DataFrame.
            initial_capital: Starting capital in INR.

        Returns:
            Dict mapping strategy name → BacktestResult.

        """
        results: dict[str, BacktestResult] = {}
        for strategy in self.STRATEGIES:
            results[strategy] = self.run_backtest(strategy, data, initial_capital)
        return results
