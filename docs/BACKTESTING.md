# Backtesting Guide

## Overview

LOHI-TRADE includes a vectorized backtesting engine for validating strategies against historical data before deploying them in paper or live trading. The engine applies realistic Indian market transaction costs and enforces minimum performance thresholds.

---

## Prerequisites

1. **Historical data downloaded** — Run the historical data manager to populate DuckDB:
   ```bash
   python -m src.data.historical_data
   ```
2. **DuckDB database populated** — Verify data exists at the configured `duckdb_path` (default: `data/historical.duckdb`)
3. **Configuration loaded** — Ensure `config/settings.yaml` has valid strategy parameters

---

## Quick Start

### Run a Single Strategy Backtest

```python
from src.backtesting.backtesting_engine import BacktestingEngine
from src.data.historical_data import HistoricalDataManager
from src.utils.config import load_config

config = load_config()
data_manager = HistoricalDataManager(config)
engine = BacktestingEngine(config, data_manager)

result = engine.run_backtest(
    symbol="RELIANCE",
    strategy="mean_reversion",
    start_date="2022-01-01",
    end_date="2023-12-31"
)

print(f"Total Return: {result.total_return_pct:.2f}%")
print(f"Sharpe Ratio: {result.sharpe_ratio:.2f}")
print(f"Max Drawdown: {result.max_drawdown_pct:.2f}%")
print(f"Win Rate: {result.win_rate:.2f}%")
print(f"Profit Factor: {result.profit_factor:.2f}")
```

### Run All Strategies

```python
results = engine.run_all_strategies(
    symbol="RELIANCE",
    start_date="2022-01-01",
    end_date="2023-12-31"
)

for strategy_name, result in results.items():
    print(f"\n--- {strategy_name} ---")
    print(f"  Return: {result.total_return_pct:.2f}%")
    print(f"  Sharpe: {result.sharpe_ratio:.2f}")
    print(f"  Max DD: {result.max_drawdown_pct:.2f}%")
```

### Run Across Multiple Symbols

```python
symbols = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"]

for symbol in symbols:
    result = engine.run_backtest(
        symbol=symbol,
        strategy="trend_following",
        start_date="2023-01-01",
        end_date="2023-12-31"
    )
    print(f"{symbol}: Return={result.total_return_pct:.2f}%, Sharpe={result.sharpe_ratio:.2f}")
```

---

## Transaction Costs

The backtesting engine applies realistic Indian equity market costs to every simulated trade:

| Cost Component | Rate | Applied On | Description |
|---------------|------|------------|-------------|
| **STT** (Securities Transaction Tax) | 0.025% | Sell side only | Government tax on equity delivery/intraday |
| **Exchange Charges** | 0.00345% | Both sides | NSE transaction charges |
| **GST** | 18% | Brokerage + exchange charges | Goods & Services Tax |
| **Stamp Duty** | 0.003% | Buy side only | State stamp duty |
| **Slippage** | 0.05% | Both sides | Simulated market impact / execution slippage |

### Cost Calculation Example

For a ₹100,000 buy order followed by a ₹101,000 sell:

```
Buy side:  Exchange (₹3.45) + Stamp (₹3.00) + Slippage (₹50.00) = ₹56.45
Sell side: STT (₹25.25) + Exchange (₹3.48) + Slippage (₹50.50) = ₹79.23
GST:       18% × (Exchange buy + Exchange sell) = ₹1.25
Total:     ₹136.93
```

---

## Performance Metrics

The engine calculates the following metrics for each backtest run:

| Metric | Formula | Description |
|--------|---------|-------------|
| **Sharpe Ratio** | `(annualized_return − risk_free_rate) / annualized_volatility` | Risk-adjusted return. Risk-free rate: 6% (Indian T-bill proxy). |
| **Maximum Drawdown** | `max(peak − trough) / peak` | Largest peak-to-trough decline during the backtest period. |
| **Win Rate** | `winning_trades / total_trades × 100` | Percentage of trades that were profitable. |
| **Profit Factor** | `gross_profit / gross_loss` | Ratio of total gains to total losses. |
| **Total Return** | `(final_equity − initial_equity) / initial_equity × 100` | Overall percentage return on capital. |

---

## Minimum Thresholds

Before promoting a strategy from backtest to paper/live trading, it must meet all of these thresholds:

| Metric | Minimum | Rationale |
|--------|---------|-----------|
| Sharpe Ratio | > 1.5 | Ensures adequate risk-adjusted returns |
| Max Drawdown | < 5% | Limits capital erosion |
| Win Rate | > 45% | Ensures strategy isn't purely luck-dependent |
| Profit Factor | > 1.5 | Ensures winners meaningfully outweigh losers |

A strategy that fails any threshold should be re-tuned or discarded. These thresholds are intentionally conservative for a system trading with real capital.

---

## Trade Logs

The engine generates detailed trade-by-trade logs for analysis:

| Field | Description |
|-------|-------------|
| `trade_id` | Unique trade identifier |
| `symbol` | NSE ticker symbol |
| `strategy` | Strategy that generated the signal |
| `direction` | BUY or SELL |
| `entry_price` | Trade entry price |
| `entry_time` | Entry timestamp |
| `exit_price` | Trade exit price |
| `exit_time` | Exit timestamp |
| `exit_reason` | `stop_loss`, `target`, `trailing_stop`, or `square_off` |
| `quantity` | Number of shares |
| `gross_pnl` | P&L before costs |
| `net_pnl` | P&L after all transaction costs |
| `holding_period` | Duration of the trade |

---

## Historical Data Management

### Data Sources

| Source | Data Type | History | Update Frequency |
|--------|-----------|---------|-----------------|
| **yfinance** | Daily OHLCV | 2+ years | Daily at 6:00 PM IST |
| **Broker API** | Intraday (1m/5m) | 30 days | Daily at 6:00 PM IST |

### Storage

- **Format:** DuckDB with Parquet partitioning by date
- **Location:** Configured via `database.duckdb_path` (default: `data/historical.duckdb`)
- **Partitioning:** Data is partitioned by date for efficient range queries

### Data Operations

```python
from src.data.historical_data import HistoricalDataManager
from src.utils.config import load_config

config = load_config()
dm = HistoricalDataManager(config)

# Download historical data
dm.download_daily("RELIANCE", start="2022-01-01", end="2023-12-31")

# Detect gaps in data
gaps = dm.detect_gaps("RELIANCE")
print(f"Missing dates: {gaps}")

# Backfill missing data
dm.backfill("RELIANCE", gaps)
```

### Auto-Update

The system automatically updates historical data at **6:00 PM IST** daily (after market close + settlement). This ensures backtests always have the latest data available.

### Gap Detection and Backfill

The `HistoricalDataManager` can detect missing trading days by comparing stored dates against the NSE trading calendar. Use `detect_gaps()` to identify missing dates and `backfill()` to fill them from the appropriate data source.
