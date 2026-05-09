# Implementation Plan: LOHI-TRADE (Unified)

## Overview

Consolidated implementation plan covering the full LOHI-TRADE system: backend core, backend gateway, frontend web app, and frontend enhancements. Task completion status reflects actual implementation state.

## Tasks

### Phase 1: Backend Foundation and Infrastructure ✅

- [x] 1. Project structure, configuration, Redis/Event Bus, database, logging
  - All infrastructure complete: pyproject.toml, settings.yaml, Redis docker-compose, Event Bus, SQLite/DuckDB, structured logging
  - _Requirements: 20-28_

### Phase 2: Broker Integration and Data Ingestion ✅

- [x] 2. Broker API abstraction (Shoonya + Angel One), instrument master, WebSocket client, tick ingestion
  - All complete with property tests for reconnection, throughput, data continuity
  - _Requirements: 1, 6, 24_

### Phase 3: The Soldier - Technical Analysis Engine ✅

- [x] 3. Candle builder, indicator engine, strategy engine (Mean Reversion, Trend Following, ORB)
  - All complete with property tests for OHLCV, indicators, signals, trading hours, duplicate prevention
  - _Requirements: 2, 3, 4_

### Phase 4: The Commander - AI/NLP Engine ✅

- [x] 4. News ingestion, entity resolution, FinBERT sentiment, bias calculator
  - All complete with property tests for dedup, entity mapping, sentiment, time decay, bias classification
  - _Requirements: 5, 6, 7, 8_

### Phase 5: Execution Engine ✅

- [x] 5. RMS (9 pre-order checks), position sizer, OMS, stop-loss/target management, kill switch
  - All complete with property tests for all RMS checks, position sizing, order management, kill switch
  - _Requirements: 9, 10, 11, 12, 13, 14_

### Phase 6: User Interfaces and Monitoring ✅

- [x] 6. Streamlit dashboard, Telegram bot, system orchestration (startup/shutdown)
  - All complete with property tests for notifications, rate limiting
  - _Requirements: 18, 19, 20_

### Phase 7: Backtesting and Historical Data ✅

- [x] 7. Historical data management, backtesting engine, comprehensive backtests
  - All complete with property tests for storage, backfill, transaction costs, metrics
  - _Requirements: 15, 16_

### Phase 8: Paper Trading and Validation ✅

- [x] 8. Paper trading mode, 10-day paper test, test suite, documentation
  - All complete: paper trading, test suite (80%+ coverage), README, SETUP, ARCHITECTURE, STRATEGIES, BACKTESTING, FAQ docs
  - _Requirements: 17, 21, 27_

### Phase 9: FastAPI Backend Gateway ✅

- [x] 9. Gateway project structure, database service, REST API routers, real-time layer, analytics service
  - All complete: backend-gateway/ with all routers (positions, orders, trades, bias, signals, analytics, config, kill-switch, health, logs), Socket.IO, Redis consumer
  - _Requirements: 29, 30_

### Phase 10: Frontend - API & State Layer ✅

- [x] 10. Dependencies, TypeScript types, API client, WebSocket client, Zustand stores, React Query hooks
  - All complete: types.ts, api-client.ts, websocket-client.ts, dashboard/positions/orders/commander stores, hooks
  - _Requirements: 31_

### Phase 11: Frontend - Page Refactoring ✅

- [x] 11. React Router, page components, loading/error states, kill switch wiring
  - All complete: DashboardPage, StrategiesPage, HistoryPage, SettingsPage, LogsPage, PositionsPage, OrdersPage, AnalyticsPage, CommanderPage, SoldierPage, BacktestPage, LoginPage
  - Shared components: LoadingSkeleton, ErrorState, ConnectionStatus, ErrorBoundary, Toast
  - _Requirements: 31, 32, 33, 34, 35, 36_

### Phase 12: Frontend - Polish & Deployment ✅

- [x] 12. Environment config, Docker setup, documentation
  - .env.example, Dockerfile, docker-compose.yml updated, README updated
  - _Requirements: 28, 29_

### Phase 13: Frontend Enhancements ✅

- [x] 13. CSV Exporter
  - csv-exporter.ts with RFC 4180 escaping, integrated into Analytics/Backtest/Logs pages
  - Property tests: column/row completeness, field escaping round-trip, filename pattern, filter respect
  - _Requirements: 37_

- [x] 14. Virtual Table
  - VirtualTable.tsx with @tanstack/react-virtual, integrated into Positions/Orders/Logs/Soldier pages
  - Property tests: bounded row rendering, data ordering preservation
  - _Requirements: 38_

- [x] 15. Theme Provider and Toggle
  - theme-store.ts, theme-provider.tsx, sun/moon toggle in header
  - Property tests: toggle involution, CSS token completeness
  - _Requirements: 41_

- [x] 16. Notification Center
  - notification-store.ts, NotificationCenter.tsx, toast integration
  - Property tests: reverse chronological order, toast storage, mark-all-read, 7-day pruning, persistence round-trip
  - _Requirements: 40_

- [x] 17. Keyboard Shortcuts and Command Palette
  - shortcut-manager.ts, CommandPalette.tsx, registered in App.tsx
  - Property tests: input suppression, number key mapping
  - _Requirements: 39_

- [x] 18. Watchlist Manager
  - watchlist-store.ts, WatchlistSection.tsx in Settings page
  - Property tests: add/remove round-trip, duplicate idempotency, autocomplete matching
  - _Requirements: 42_

- [x] 19. P&L Alert Engine
  - alert-store.ts, use-pnl-alerts.ts hook, AlertsSection.tsx in Settings page
  - Property tests: threshold evaluation, once-per-session firing, CRUD round-trip
  - _Requirements: 43_

- [x] 20. Trade Journal
  - TradeJournal.tsx, backend trade_notes table and API endpoints
  - Property tests: character limit, CRUD round-trip, note icon display
  - _Requirements: 44_

- [x] 21. Mini Chart Dashboard Widgets
  - MiniChartWidget.tsx, Market Overview section in Dashboard
  - Property tests: data correctness, symbol count matching, tick updates
  - _Requirements: 45_

- [x] 22. Report Generator
  - report-generator.ts, Generate Report button in Analytics page
  - Property tests: required sections, Indian Rupee formatting
  - _Requirements: 46_

- [x] 23. Final wiring and integration
  - NotificationCenter and ThemeToggle in App.tsx header
  - Alert Engine wired to WebSocket
  - Ctrl+E shortcut wired to CSV export

## Notes

- All backend core tasks (Phases 1-8) are complete with property-based tests
- Backend gateway (Phase 9) is fully implemented
- Frontend pages and state layer (Phases 10-12) are complete
- All 10 frontend enhancements (Phase 13) are complete with property tests
- The lohi-trade-frontend spec tasks were superseded by the actual implementation in Phases 10-12
- The frontend-backend-integration spec was completed as Phase 9
- The frontend-enhancements spec was completed as Phase 13
