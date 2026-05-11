# Requirements Document: LOHI-TRADE (Unified)

## Introduction

LOHI-TRADE is an Event-Driven, Hybrid Algorithmic Trading System designed for Indian Equity Markets (NSE/BSE). The system combines mathematical precision through technical analysis ("The Soldier") with artificial intelligence-driven sentiment analysis ("The Commander") to generate high-quality trading signals. It operates locally on MacBook Pro M3 Pro hardware, targeting intraday trading with strict risk management controls.

The system includes:
- **Backend Core**: Python-based trading engine with Redis Streams event bus, SQLite/DuckDB storage, broker integrations (Shoonya/Angel One), and Telegram notifications
- **Backend Gateway**: FastAPI service bridging the frontend with Redis Streams and SQLite
- **Frontend Web App**: React 18 + Vite + TypeScript SPA with Radix UI components, Recharts, Zustand state management, and real-time WebSocket updates
- **Frontend Enhancements**: CSV exports, virtual scrolling, keyboard shortcuts, notification center, theme toggle, watchlist management, P&L alerts, trade journal, mini chart widgets, and PDF report generation

## Glossary

- **The_Soldier**: Fast technical analysis engine for real-time market data processing and signal generation
- **The_Commander**: AI/NLP engine for news sentiment analysis and bias signal generation
- **RMS**: Risk Management System - 9 pre-order validation checks
- **OMS**: Order Management System - order placement, fill monitoring, stop-loss management
- **Event_Bus**: Redis Streams-based message broker
- **Kill_Switch**: Emergency mechanism to halt all trading activity
- **API_Gateway**: FastAPI backend service bridging frontend with Redis/SQLite
- **CSV_Exporter**: Utility for CSV export with RFC 4180 compliance
- **Virtual_Scroller**: Windowed rendering for large tables
- **Shortcut_Manager**: Global keyboard shortcut dispatcher
- **Notification_Center**: Persistent notification history panel
- **Theme_Provider**: Dark/light theme management context
- **Watchlist_Manager**: Symbol monitoring UI and state
- **Alert_Engine**: P&L threshold evaluation engine
- **Trade_Journal**: Trade notes UI and backend storage
- **Mini_Chart_Widget**: Per-symbol sparkline dashboard widget
- **Report_Generator**: End-of-day PDF/print report composer

---

## Part A: Backend Core Requirements (Req 1-28)

### Requirement 1: Real-Time Market Data Ingestion
**User Story:** As a trader, I want the system to receive real-time market data from NSE.
#### Acceptance Criteria
1. Establish WebSocket connections within 30 seconds of market open (9:15 AM IST)
2. Publish ticks to Event_Bus within 10 milliseconds
3. Reconnect with exponential backoff (1s, 2s, 4s, 8s, max 30s)
4. Heartbeat alert if no ticks for 5 seconds during market hours
5. Support Shoonya (primary) and Angel One (backup) broker APIs
6. Maintain data continuity during broker switching
7. Process minimum 1000 ticks/second without data loss

### Requirement 2: Candle Building and Time-Series Aggregation
**User Story:** As a technical analyst, I want tick data aggregated into OHLCV candles.
#### Acceptance Criteria
1. Build candles for 1-minute, 5-minute, and 15-minute timeframes
2. Publish completed candles within 100 milliseconds
3. Correctly calculate OHLCV values
4. Handle market gaps by carrying forward last known price
5. Maintain candle state in memory for current trading day
6. Rebuild candles from tick history on restart

### Requirement 3: Technical Indicator Calculation
#### Acceptance Criteria
1. Calculate RSI(14), MACD(12,26,9), Bollinger Bands(20,2), VWAP, EMA(9,21), Supertrend(7,3), ATR(14) using pandas-ta
2. Wait for minimum required periods before calculating
3. Calculate independently per symbol
4. Publish within 50ms of candle completion
5. Log errors and continue on failure

### Requirement 4: Trading Strategy Signal Generation
#### Acceptance Criteria
1. Three strategies: Mean Reversion, Trend Following, Opening Range Breakout
2. Include entry price, stop loss (ATR-based), and target in every signal
3. Publish signals to Event_Bus for RMS validation
4. No signals outside trading hours (9:30 AM - 3:10 PM IST)
5. Check for duplicate positions before generating signal

### Requirement 5: News Ingestion and Deduplication
#### Acceptance Criteria
1. Poll RSS feeds (MoneyControl, Economic Times, LiveMint) every 60 seconds
2. Deduplicate using content hash comparison
3. Publish unique articles within 5 seconds
4. Store in SQLite

### Requirement 6: Entity Resolution and Ticker Mapping
#### Acceptance Criteria
1. Extract company names using spaCy NER
2. Map to NSE tickers with fuzzy matching (500+ companies)
3. Associate articles with all identified tickers
4. Log unmapped entities

### Requirement 7: Sentiment Analysis Using FinBERT
#### Acceptance Criteria
1. FinBERT via ONNX Runtime (Apple M3 Neural Engine)
2. Classify as POSITIVE/NEGATIVE/NEUTRAL with confidence scores
3. Process within 2 seconds
4. Apply Indian market keyword boosters
5. Default to NEUTRAL on failure

### Requirement 8: Bias Calculation with Time Decay
#### Acceptance Criteria
1. Aggregate sentiment from last 24 hours with exponential decay (4-hour half-life)
2. Classify: BULLISH (>0.2), BEARISH (<-0.2), NEUTRAL
3. Recalculate every 5 minutes during market hours
4. Store bias history in SQLite

### Requirement 9: Signal Filtering Using AI Bias
#### Acceptance Criteria
1. Reject BUY signals when bias is BEARISH
2. Reject SELL signals when bias is BULLISH
3. Default to NEUTRAL when bias unavailable
4. Log all bias-based rejections

### Requirement 10: Risk Management System (9 Pre-Order Checks)
#### Acceptance Criteria
1. Daily loss limit (2% of capital), position count (max 5), position size (max 20%), order count (max 20/day), cooldown (5 min after loss), kill switch, volatility guard (Nifty -2% in 10 min), trading hours, bias filter
2. Forward to OMS within 50ms on pass
3. Log rejections to Event_Bus and SQLite

### Requirement 11: Position Sizing
#### Acceptance Criteria
1. Quantity = (capital × risk_per_trade) / (entry - stop_loss)
2. Max risk 1%, max position 20%, round to integer, reject if < 1

### Requirement 12: Order Management System
#### Acceptance Criteria
1. Place via broker API within 100ms, MIS product type
2. Rate limit 8 req/sec, retry 2x on rejection
3. Store in SQLite, poll status every 1s
4. Cancel unfilled orders after 60 seconds

### Requirement 13: Stop-Loss and Target Management
#### Acceptance Criteria
1. Place stop-loss and target immediately after fill
2. Trailing stop: move up by 50% of profit
3. OCO logic, force square-off at 3:15 PM IST

### Requirement 14: Kill Switch
#### Acceptance Criteria
1. State in Redis, reject all orders when active
2. Cancel pending orders within 5 seconds
3. Auto-activate on Nifty -2%/10min or daily loss > 2%
4. Telegram notification, require manual deactivation

### Requirement 15: Historical Data Management
#### Acceptance Criteria
1. yfinance daily data, Shoonya intraday (30 days)
2. DuckDB + Parquet partitioned by date
3. Backfill missing ranges, update daily at 6 PM IST

### Requirement 16: Backtesting Engine
#### Acceptance Criteria
1. vectorbt, all three strategies, realistic Indian transaction costs + 0.05% slippage
2. Metrics: Sharpe, Max DD, Win Rate, Profit Factor
3. Thresholds: Sharpe > 1.5, Max DD < 5%, Win Rate > 45%

### Requirement 17: Paper Trading Mode
#### Acceptance Criteria
1. Config flag, simulate fills with next tick + 100-500ms delay
2. Separate database (paper_trades.db), "PAPER" prefix in notifications

### Requirement 18: Streamlit Dashboard
#### Acceptance Criteria
1. P&L, positions, signals, trades, bias, health indicators
2. Kill switch button, auto-refresh every 5 seconds

### Requirement 19: Telegram Notifications
#### Acceptance Criteria
1. Trade entry/exit, kill switch, daily loss warning, daily summary
2. Commands: /status, /pnl, /killswitch
3. Rate limit: 20 messages/hour

### Requirement 20: System Orchestration
#### Acceptance Criteria
1. Startup: Redis → health checks → broker login → instrument master → WebSocket subscribe
2. Shutdown: close positions → cancel orders → disconnect → backup DB
3. Auto-shutdown at 3:45 PM

### Requirements 21-28: Logging, Configuration, Database, Instrument Master, Performance, Error Handling, Testing, Deployment
- Structured rotating logs, settings.yaml with env overrides, SQLite + DuckDB, daily instrument master download, M3 optimization, circuit breaker pattern, 80%+ coverage, Docker containerization

---

## Part B: Backend Gateway Requirements (Req 29-30)

### Requirement 29: FastAPI Backend Gateway
#### Acceptance Criteria
1. REST endpoints for all data: positions, orders, trades, signals, bias, news, logs, config, health
2. Consume from existing Redis Streams without modifying stream structure
3. Query existing SQLite tables without schema changes
4. Publish user commands to stream:commands
5. Run on port 8000 with CORS, JWT auth middleware, rate limiting (100 req/min/user)
6. WebSocket endpoint at /ws via Socket.IO
7. Health check at GET /api/health

### Requirement 30: WebSocket Real-Time Layer
#### Acceptance Criteria
1. Socket.IO server emitting: position_update, order_update, signal_generated, bias_update, price_tick, kill_switch_toggle
2. Consume Redis Stream messages and forward as Socket.IO events
3. Auto-reconnect, connection status indicator, message rate limiting

---

## Part C: Frontend Web App Requirements (Req 31-36)

### Requirement 31: Frontend Architecture and Routing
#### Acceptance Criteria
1. React Router for all pages (Dashboard, Positions, Orders, Strategies, History, Settings, Logs, Analytics, Commander, Soldier, Backtest)
2. API calls via axios, Zustand stores, React Query caching
3. Loading skeletons and error states with retry
4. Preserve Figma UI design

### Requirement 32: Real-Time Dashboard
#### Acceptance Criteria
1. P&L (realized/unrealized/total) via WebSocket, color coded
2. Key stats, system health, kill switch toggle
3. Responsive (320px minimum)

### Requirement 33: Data Pages (Positions, Orders, History, Strategies, Settings, Logs)
- Fetch from API, tables with sorting/filtering, WebSocket updates, responsive, loading/error states

### Requirement 34: Analytics Page
- Equity curve, daily P&L, strategy breakdown, trade distribution, CSV export, date range selection

### Requirement 35: Commander Dashboard
- Bias table, news articles, sentiment timeline, rejected signals

### Requirement 36: Soldier Dashboard
- Signals table, live price chart with indicators, timeframe selection, strategy stats

---

## Part D: Frontend Enhancement Requirements (Req 37-46)

### Requirement 37: CSV Export
- Per-page columns, apply filters, RFC 4180 escaping, lohi-trade-{page}-{date}.csv naming

### Requirement 38: Virtual Scrolling
- Windowed rendering (>50 rows), 10-row buffer, keyboard navigation, preserve sort/filter

### Requirement 39: Global Keyboard Shortcuts
- Ctrl+K command palette, Escape close, Ctrl+Shift+K kill switch, Ctrl+E export, Shift+? help

### Requirement 40: Notification Center
- Bell icon + unread badge, 100 notifications, localStorage persistence, 7-day auto-prune

### Requirement 41: Dark/Light Theme Toggle
- CSS custom properties, localStorage persistence, default dark, WCAG AA contrast for light

### Requirement 42: Watchlist / Symbol Selector
- Settings page, autocomplete from instrument master, save via PUT /api/config

### Requirement 43: P&L Alerts and Thresholds
- Absolute and percentage thresholds, once-per-session firing, localStorage + backend sync

### Requirement 44: Trade Journal
- Notes panel on History page, 2000 char limit, backend trade_notes table, note icon indicator

### Requirement 45: Mini Chart Dashboard Widgets
- Sparkline per symbol, last 50 ticks, real-time updates, responsive grid

### Requirement 46: PDF End-of-Day Report
- Generate Report button, print dialog, Indian Rupee format (₹), all key metrics
