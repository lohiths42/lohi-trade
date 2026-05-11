# Frequently Asked Questions

## Setup Issues

### Q: Redis connection refused
**A:** Ensure Redis is running:
```bash
docker-compose up -d redis
```
Verify with:
```bash
redis-cli ping
# Expected: PONG
```
If using a custom port, check `redis.port` in `config/settings.yaml`. See [docs/REDIS_SETUP.md](REDIS_SETUP.md) for detailed Redis configuration.

---

### Q: Broker login fails
**A:** Check these in order:
1. Verify credentials in `.env` file match your broker account
2. Confirm the broker API service is online (check broker's status page)
3. Ensure TOTP/2FA is configured correctly — the TOTP secret must be the base32 seed, not the 6-digit code
4. Check if your API session was invalidated (some brokers allow only one active session)

---

### Q: spaCy model not found
**A:** Download the required model:
```bash
python -m spacy download en_core_web_sm
```

> **Note:** spaCy may have compatibility issues with Python 3.14. If you encounter installation errors, try Python 3.11 or 3.12.

---

### Q: FinBERT ONNX model not found
**A:** Run the conversion script to download and convert the model:
```bash
python scripts/convert_finbert_onnx.py
```
This downloads the FinBERT model from Hugging Face and converts it to ONNX format for faster inference. The output is saved to `models/finbert.onnx`.

---

### Q: Import errors or missing dependencies
**A:** Install all dependencies:
```bash
pip install -r requirements.txt
```
If using a virtual environment, make sure it's activated first.

---

## Trading Issues

### Q: No signals being generated
**A:** Check these common causes:

1. **Market hours** — Signals are only generated between 9:30 AM and 3:10 PM IST. Outside these hours, the signal pipeline is inactive.
2. **Insufficient candle history** — Indicators like RSI(14) and BB(20) need at least 20 completed candles before producing values. Wait ~100 minutes after market open.
3. **Strategy conditions not met** — All entry conditions must be true simultaneously. Use `DEBUG` logging to see individual indicator values.
4. **Kill switch active** — Check Redis: `redis-cli GET kill_switch:active`. If `true`, no signals will pass RMS.
5. **Bias filtering** — The Commander may be rejecting signals. Check current bias in the dashboard or logs.

---

### Q: Orders being rejected by RMS
**A:** Check the RMS rejection logs in `logs/` or the SQLite audit table. Common rejection reasons:

| Rejection Reason | Fix |
|-----------------|-----|
| `kill_switch_active` | Deactivate via dashboard or Telegram `/killswitch` |
| `outside_trading_hours` | Wait for trading window (9:30 AM – 3:10 PM) |
| `daily_loss_limit_exceeded` | Daily loss > 2% of capital. Resets next trading day. |
| `max_positions_reached` | Wait for existing positions to close (max 5) |
| `position_size_exceeded` | Reduce position size or increase capital |
| `max_orders_reached` | 20 orders/day limit reached. Resets next day. |
| `cooldown_active` | Wait 5 minutes after last losing trade |
| `volatility_guard_triggered` | Nifty dropped > 2% in 10 min. Wait for conditions to normalize. |
| `bias_filter_rejected` | Commander's sentiment conflicts with signal direction |

---

### Q: Kill switch activated unexpectedly
**A:** The kill switch auto-triggers under two conditions:
1. **Nifty volatility:** Nifty 50 drops more than 2% within a 10-minute window
2. **Daily loss:** Cumulative daily loss exceeds 2% of total capital

The kill switch **requires manual deactivation** by design. This prevents the system from resuming trading during dangerous market conditions.

**To deactivate:**
- Streamlit dashboard: Click the "Deactivate Kill Switch" button
- Telegram: Send `/killswitch` command to the bot

---

### Q: Paper trading not working
**A:** Verify these settings in `config/settings.yaml`:
```yaml
paper_trading:
  enabled: true
  simulated_fill_delay_ms: [100, 500]
  simulated_slippage_pct: 0.05
```
Paper trades are stored in the main SQLite database (`data/lohi_trade.db`) with a `paper_trade` flag. Ensure the database is writable.

---

## Performance Issues

### Q: High tick processing latency
**A:** Potential causes and fixes:
1. **CPU saturation** — Check system CPU usage. The Soldier's indicator calculations are CPU-bound.
2. **Redis latency** — Run `redis-cli --latency` to check. Should be < 1ms.
3. **Too many symbols** — Reduce the symbol list in `settings.yaml`. Each symbol adds processing overhead.
4. **Debug logging** — Set `logging.level: INFO` instead of `DEBUG` in production.

---

### Q: Memory usage too high
**A:** The system logs a warning if RSS (Resident Set Size) exceeds 4GB. Common causes:
1. **Candle history accumulation** — Only the current trading day's candles are kept in memory. If memory grows, check for leaks in custom modifications.
2. **Too many symbols** — Each symbol maintains its own candle and indicator buffers.
3. **FinBERT model** — The ONNX model uses ~500MB. This is expected.

---

## Data Issues

### Q: Historical data has gaps
**A:** Use the built-in gap detection and backfill:
```python
from src.data.historical_data import HistoricalDataManager
from src.utils.config import load_config

config = load_config()
dm = HistoricalDataManager(config)

# Detect missing dates
gaps = dm.detect_gaps("RELIANCE")
print(f"Missing dates: {gaps}")

# Backfill from data source
dm.backfill("RELIANCE", gaps)
```
The daily auto-update runs at 6:00 PM IST and should prevent future gaps.

---

### Q: DuckDB query errors
**A:** Common fixes:
1. Ensure historical data is in Parquet format — run the data manager to re-download if needed
2. Check file permissions on the `data/` directory
3. Verify the `database.duckdb_path` in settings.yaml points to the correct file
4. If the database is corrupted, delete it and re-download historical data

---

## Monitoring

### Q: Streamlit dashboard not loading
**A:** Start the dashboard:
```bash
streamlit run src/ui/dashboard.py
```
Access at [http://localhost:8501](http://localhost:8501). If the port is in use, Streamlit will suggest an alternative.

Ensure Redis and SQLite are accessible — the dashboard reads from both.

---

### Q: Telegram notifications not arriving
**A:** Troubleshooting steps:
1. **Verify bot token** — Ensure `TELEGRAM_BOT_TOKEN` in `.env` is correct (get from @BotFather)
2. **Verify chat ID** — Ensure `TELEGRAM_CHAT_ID` is correct (use @userinfobot to find your ID)
3. **Rate limit** — The bot is limited to 20 messages/hour. Check if the limit was hit in logs.
4. **Bot permissions** — If using a group chat, ensure the bot is added to the group and has send permissions.
5. **Network** — Ensure the machine has outbound HTTPS access to `api.telegram.org`.

---

## Maintenance

### Q: How to backup data?
**A:** Backups happen automatically:
- **Schedule:** Daily at 4:00 PM IST (configurable via `database.backup_time`)
- **Location:** `data/backups/` (configurable via `database.backup_path`)
- **What's backed up:** SQLite database (`data/lohi_trade.db`)

For manual backup:
```bash
cp data/lohi_trade.db data/backups/lohi_trade_$(date +%Y%m%d).db
```

DuckDB historical data is not backed up automatically (it can be re-downloaded).

---

### Q: How to update the instrument master?
**A:** The instrument master downloads automatically at system startup each trading day.

For manual update:
```python
from src.ingestion.instrument_master import InstrumentMaster

im = InstrumentMaster()
im.download()
```

Or from the command line:
```bash
python -c "from src.ingestion.instrument_master import InstrumentMaster; im = InstrumentMaster(); im.download()"
```

---

### Q: How to reset the kill switch?
**A:** The kill switch can only be deactivated manually (by design):

- **Streamlit dashboard:** Click the "Deactivate Kill Switch" button on the dashboard
- **Telegram:** Send the `/killswitch` command to the bot

The kill switch **cannot auto-reset**. This is an intentional safety feature to ensure a human reviews market conditions before resuming trading.

---

### Q: How to add a new symbol to trade?
**A:** Add the NSE symbol to the `symbols` list in `config/settings.yaml`:
```yaml
symbols:
  - RELIANCE
  - TCS
  - NEWSTOCK    # Add here
```
Restart the system for the change to take effect. The instrument master will automatically resolve the new symbol's broker token.

---

### Q: How to change strategy parameters?
**A:** Edit the strategy section in `config/settings.yaml`. For example, to make mean reversion more aggressive:
```yaml
strategies:
  mean_reversion:
    rsi_oversold: 35        # Was 30 — triggers earlier
    volume_multiplier: 1.2   # Was 1.5 — lower volume requirement
```
Always backtest parameter changes before deploying. See [docs/BACKTESTING.md](BACKTESTING.md) for the backtesting guide.

---

### Q: How to run in live trading mode?
**A:** Switch from paper to live trading:
```yaml
paper_trading:
  enabled: false    # Change from true to false
```

**Before going live, ensure:**
1. All strategies pass backtest minimum thresholds (Sharpe > 1.5, Max DD < 5%)
2. Paper trading has been validated for at least 2 weeks
3. Broker credentials are correct and API access is active
4. Kill switch is tested and working
5. Telegram notifications are configured for real-time alerts
