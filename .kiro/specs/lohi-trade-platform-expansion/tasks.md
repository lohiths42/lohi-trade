# Implementation Plan: LOHI-TRADE Platform Expansion

## Overview

Incremental implementation plan expanding the existing LOHI-TRADE system into a multi-user, cloud-deployed platform. Each task builds on previous steps. The existing base system (broker integration, trading engine, strategies, risk management, OMS, backtesting, paper trading, Telegram bot, web dashboard, Redis/SQLite infrastructure) is already complete — these tasks cover only the new expansion features.

Backend: Python (FastAPI, asyncpg). Frontend: TypeScript (React, Vite). Mobile: Swift/SwiftUI (iOS), Kotlin/Jetpack Compose (Android). Infrastructure: AWS CDK (Python).

## Tasks

- [x] 1. PostgreSQL schema and database migration
  - [x] 1.1 Create PostgreSQL schema with all new tables
    - Write Alembic migration creating: users, social_logins, refresh_tokens, pan_verifications, kyc_verifications, dmat_accounts, bank_accounts, fund_transactions, trading_balances, securities, security_fundamentals, security_technicals, watchlists, watchlist_items, screener_presets, corporate_actions, broker_connections, chatbot_sessions, api_request_log
    - Add user_id UUID column to existing tables (trades, orders, sentiment_log, bias_log, audit_log, ml_training_samples, ml_predictions)
    - Create all indexes: idx_securities_symbol, idx_securities_sector, idx_securities_status, full-text search GIN index on securities
    - Enable Row-Level Security (RLS) policies on all user-scoped tables
    - _Requirements: 23.1, 29.4, 31.4_

  - [x] 1.2 Implement SQLite-to-PostgreSQL migration script
    - Create `scripts/migrate_sqlite_to_postgres.py` with `SQLiteToPostgresMigrator` class
    - Implement idempotent migration: read SQLite → write PostgreSQL with user_id column assigned to admin user
    - Implement validation: compare row counts and checksums per table between SQLite and PostgreSQL
    - Support re-runs without duplicating data
    - _Requirements: 31.1, 31.2, 31.3, 31.5, 31.6_

  - [x] 1.3 Write property tests for migration round-trip
    - **Property 1: Migration round-trip consistency** — exporting from SQLite, importing to PostgreSQL, then exporting from PostgreSQL produces equivalent data sets
    - **Validates: Requirements 31.5**

  - [x] 1.4 Write property tests for RLS isolation
    - **Property 2: User data isolation** — queries with user_id context only return rows belonging to that user
    - **Validates: Requirements 29.4**

- [x] 2. Checkpoint — Database foundation
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Account creation, authentication, and social login
  - [x] 3.1 Implement AccountService with email/password registration
    - Create `backend-gateway/app/services/account_service.py`
    - Implement `register_email()`: validate email, hash password (bcrypt), store user, send OTP for email verification (OTP valid 15 minutes)
    - Implement `login_email()`: verify credentials, issue JWT access token (15-min expiry) + refresh token (30-day expiry)
    - Implement `refresh_token()`: validate refresh token, issue new access token
    - Enforce password policy: min 8 chars, 1 uppercase, 1 lowercase, 1 digit, 1 special char
    - Collect Indian mobile phone number (10 digits) during registration
    - _Requirements: 29.1, 29.2, 32.1, 32.6, 32.7, 32.9_

  - [x] 3.2 Implement Google OAuth and Apple Sign-In
    - Implement `login_google()`: verify Google ID token via Google Identity Services, extract email/name/picture, create or link account
    - Implement `login_apple()`: verify Apple auth code via Sign in with Apple REST API, handle email-sharing and email-hidden scenarios
    - Implement `link_social_provider()`: link social provider to existing account when same email exists
    - Store only provider_id and provider type — never store social access tokens
    - _Requirements: 32.2, 32.3, 32.4, 32.5, 32.7_

  - [x] 3.3 Create auth API router endpoints
    - Create `backend-gateway/app/routers/auth_v2.py` with endpoints: POST /auth/register, POST /auth/login, POST /auth/google, POST /auth/apple, POST /auth/refresh, POST /auth/logout
    - Add JWT middleware that sets `app.current_user_id` for RLS
    - Log all auth events (login, logout, failed attempts, token refresh) for security audit
    - _Requirements: 29.5, 29.7, 32.6, 32.8_

  - [x] 3.4 Implement role-based access control (RBAC)
    - Add RBAC middleware enforcing ADMIN, TRADER, VIEWER roles on all endpoints
    - Implement account deactivation by ADMIN (prevents login, halts trading)
    - _Requirements: 29.3, 29.6_

  - [x] 3.5 Write property tests for authentication
    - **Property 3: Password policy enforcement** — all accepted passwords satisfy min 8 chars, 1 upper, 1 lower, 1 digit, 1 special
    - **Property 4: JWT token lifecycle** — access tokens expire after 15 minutes, refresh tokens after 30 days
    - **Validates: Requirements 29.2, 32.6**

- [x] 4. API rate limiting and security hardening
  - [x] 4.1 Implement rate limiting middleware
    - Create Redis-based sliding window rate limiter: 100 req/min for read endpoints, 30 req/min for write endpoints per user
    - Return HTTP 429 with Retry-After header when limit exceeded
    - Store rate counters in Redis sorted sets: `rate:{user_id}:read`, `rate:{user_id}:write`
    - _Requirements: 30.1, 30.2_

  - [x] 4.2 Implement security middleware
    - Add CORS middleware allowing only platform web domain and mobile app origins
    - Add input sanitization middleware (SQL injection, XSS, command injection prevention)
    - Add response compression middleware (gzip/brotli for responses >1KB)
    - Add request logging middleware: user_id, endpoint, method, status, response_time
    - Enforce HTTPS/TLS 1.2+ (ALB-level, configure in infra)
    - _Requirements: 30.3, 30.4, 30.5, 30.7, 34.7_

  - [x] 4.3 Write property tests for rate limiting
    - **Property 5: Rate limit enforcement** — after N requests in a window, subsequent requests return 429
    - **Validates: Requirements 30.1, 30.2**

- [x] 5. Checkpoint — Auth and security
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. PAN/KYC/DMAT verification services
  - [x] 6.1 Implement PAN verification service
    - Create `backend-gateway/app/services/verification_service.py` with `PANVerificationService`
    - Implement `validate_format()`: regex [A-Z]{5}[0-9]{4}[A-Z]{1}
    - Implement `verify_pan()`: call NSDL/UTI API with 3x exponential backoff retry, 10-second timeout
    - Implement `mask_pan()`: display only first 2 and last 2 chars (AB******Z1)
    - Implement `encrypt_pan()` / `decrypt_pan()`: AES-256 encryption at rest
    - Store verified PAN status, holder name, verification timestamp
    - Return specific rejection reasons (invalid PAN, name mismatch, inactive PAN)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7_

  - [x] 6.2 Implement KYC verification service
    - Add `KYCService` class to verification_service.py
    - Require PAN verification completed before KYC initiation
    - Collect: full name, DOB, address, Aadhaar (optional), government ID photo
    - Validate document quality: min 300 DPI, 100KB-5MB, JPEG/PNG
    - Submit to KYC provider API (DigiLocker/KRA) for identity validation
    - Support statuses: NOT_STARTED, PENDING, VERIFIED, REJECTED
    - Queue failed submissions for retry, notify user of delay
    - AES-256 encrypt all identity documents at rest
    - Delete uploaded document images within 30 days of successful verification
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10_

  - [x] 6.3 Implement DMAT account linking service
    - Add `DMATService` class to verification_service.py
    - Require KYC status VERIFIED before DMAT linking
    - Validate CDSL format (16-digit numeric) and NSDL format (IN + 14 alphanum)
    - Verify against depository participant API within 15 seconds
    - Store linked DMAT account ID, depository name, DP name
    - Enforce max 3 DMAT accounts per user
    - Verify no open positions before unlinking
    - AES-256 encrypt DMAT account numbers at rest
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_

  - [x] 6.4 Create verification API router
    - Create `backend-gateway/app/routers/verification.py` with endpoints: POST /verify/pan, GET /verify/pan/status, POST /verify/kyc, GET /verify/kyc/status, POST /verify/dmat, DELETE /verify/dmat/{id}, GET /verify/dmat/list
    - All endpoints require authenticated user with TRADER or ADMIN role
    - _Requirements: 1-3 (all)_

  - [x] 6.5 Write property tests for PAN format validation
    - **Property 6: PAN format validation** — all strings matching [A-Z]{5}[0-9]{4}[A-Z]{1} are accepted, all others rejected
    - **Validates: Requirements 1.1**

  - [x] 6.6 Write property tests for PAN masking
    - **Property 7: PAN masking correctness** — masked PAN always shows exactly first 2 and last 2 characters with 6 asterisks
    - **Validates: Requirements 1.7**

  - [x] 6.7 Write property tests for DMAT format validation
    - **Property 8: DMAT format validation** — CDSL (16-digit) and NSDL (IN + 14 alphanum) formats correctly identified
    - **Validates: Requirements 3.2**

- [x] 7. Bank account and fund management services
  - [x] 7.1 Implement bank account registration and verification
    - Add `BankAccountService` class to `backend-gateway/app/services/bank_service.py`
    - Collect: account holder name, account number, IFSC code, bank name, account type (savings/current)
    - Validate IFSC code against RBI IFSC directory
    - Initiate penny drop verification (₹1 credit) and confirm holder name matches KYC name
    - Enforce max 3 bank accounts per user, designate one as primary
    - AES-256 encrypt bank account numbers at rest
    - Require KYC VERIFIED status before registration
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9_

  - [x] 7.2 Implement fund deposit service
    - Implement `initiate_deposit()`: support UPI, net banking, NEFT/RTGS
    - Generate UPI payment link/QR code valid for 15 minutes
    - Credit trading balance within 30 seconds of payment confirmation
    - Enforce min ₹100, max ₹10,00,000 per deposit
    - Record transactions: amount, method, reference, timestamp, status (INITIATED, PROCESSING, COMPLETED, FAILED)
    - Notify user on failure with reason
    - Implement daily reconciliation at 6:00 PM IST with payment gateway settlement reports
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8_

  - [x] 7.3 Implement fund withdrawal service
    - Implement `initiate_withdrawal()`: verify withdrawable balance (total - margin blocked)
    - Process only to VERIFIED bank accounts
    - Enforce min ₹100, daily max ₹25,00,000
    - Initiate NEFT/IMPS transfer to designated bank account
    - Process before 4:00 PM IST same day, after 4:00 PM next business day
    - Record transactions with status tracking
    - Reverse debit on transfer failure and notify user
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8_

  - [x] 7.4 Create bank/fund API router
    - Create `backend-gateway/app/routers/bank.py` with endpoints: POST /bank/register, GET /bank/list, PUT /bank/{id}/primary, POST /fund/deposit, POST /fund/withdraw, GET /fund/transactions, GET /fund/balance
    - _Requirements: 4-6 (all)_

  - [x] 7.5 Write property tests for fund management
    - **Property 9: Withdrawable balance invariant** — withdrawable balance always equals total balance minus blocked margin, never negative
    - **Property 10: Deposit/withdrawal limits** — deposits outside ₹100-₹10,00,000 rejected; withdrawals exceeding daily ₹25,00,000 rejected
    - **Validates: Requirements 5.5, 6.1, 6.3, 6.8**

- [x] 8. Checkpoint — Verification and fund management
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Stock universe and sector classification
  - [x] 9.1 Implement stock universe service
    - Create `backend-gateway/app/services/stock_universe_service.py` with `StockUniverseService`
    - Implement `search_securities()`: full-text search by symbol, name, ISIN using PostgreSQL GIN index, target <200ms
    - Implement `list_securities()`: paginated listing with filters (exchange, sector, market_cap_category, status)
    - Implement `refresh_catalog()`: daily refresh at 7:00 AM IST from NSE/BSE data sources
    - Handle new listings (add within 24 hours) and delistings (set INACTIVE, prevent new orders)
    - Store per security: symbol, ISIN, company name, exchange, sector, industry, market_cap_category, listing_date, face_value, status
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7_

  - [x] 9.2 Implement sector classification and aggregation
    - Classify all securities into 15 sectors: Pharma, IT/Technology, AI/Deep Tech, Metals & Mining, Banking & Finance, FMCG, Energy, Automobile, Telecom, Real Estate, Infrastructure, Chemicals, Media & Entertainment, Insurance, Miscellaneous
    - Implement sub-industry classification within each sector
    - Implement `get_sector_aggregate()`: total market cap, stock count, top 5 gainers/losers per sector
    - Support filtering within sector by market cap range, PE ratio range, dividend yield range
    - Update classifications quarterly
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

  - [x] 9.3 Create stock universe API router
    - Create `backend-gateway/app/routers/stock_universe.py` with endpoints: GET /stocks/search, GET /stocks, GET /stocks/{symbol}, GET /sectors, GET /sectors/{name}, GET /sectors/{name}/stocks
    - _Requirements: 7.6, 7.7, 8.3, 8.4, 8.5_

  - [x] 9.4 Write property tests for stock search
    - **Property 11: Search response time** — search queries return results within 200ms for any query string
    - **Property 12: Search completeness** — searching by exact symbol always returns that security if it exists and is active
    - **Validates: Requirements 7.6**

- [x] 10. Watchlist management
  - [x] 10.1 Implement watchlist service
    - Create `backend-gateway/app/services/watchlist_service.py` with `WatchlistService`
    - Implement CRUD: create, rename, delete, add security, remove security, reorder securities
    - Enforce max 20 watchlists per user, max 100 securities per watchlist
    - Validate security exists and is actively traded before adding
    - Implement `get_watchlist_with_prices()`: return LTP, change%, volume for all securities, target <500ms
    - Implement pre-built watchlists: Nifty 50, Nifty Bank, Nifty IT, Nifty Pharma, Nifty Next 50
    - Persist in PostgreSQL, sync across web and mobile
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7_

  - [x] 10.2 Create watchlist API router
    - Create `backend-gateway/app/routers/watchlist.py` with endpoints: POST /watchlists, GET /watchlists, GET /watchlists/{id}, PUT /watchlists/{id}, DELETE /watchlists/{id}, POST /watchlists/{id}/securities, DELETE /watchlists/{id}/securities/{symbol}, GET /watchlists/prebuilt
    - _Requirements: 9.4, 9.7_

  - [x] 10.3 Write property tests for watchlist limits
    - **Property 13: Watchlist capacity enforcement** — adding beyond 20 watchlists or 100 securities per watchlist is rejected
    - **Validates: Requirements 9.1, 9.2**

- [x] 11. Stock screener engine
  - [x] 11.1 Implement screener engine
    - Create `backend-gateway/app/services/screener_service.py` with `ScreenerEngine`
    - Implement `screen()`: apply fundamental + technical + return filters with AND logic, paginated + sorted results, target <2s
    - Support all fundamental params: PE, PB, market cap, dividend yield, EPS, ROE, debt-to-equity, revenue growth (1y/3y), profit growth (1y/3y)
    - Support all technical params: 52-week high/low proximity, RSI-14, MA crossovers (50/200), avg volume, price change (1d/1w/1m/3m/6m/1y/3y/5y)
    - Support return params: 1y return, 3y CAGR, 5y CAGR
    - Implement `save_preset()`: max 10 custom presets per user
    - Implement pre-built templates: High Dividend Yield, Undervalued Large Caps, Momentum Stocks, Low PE Growth Stocks, 52-Week Breakout Candidates
    - Implement `export_csv()`: export all matching results with all displayed columns
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 11.1, 11.2, 11.3, 11.5, 11.6_

  - [x] 11.2 Create screener API router
    - Create `backend-gateway/app/routers/screener.py` with endpoints: POST /screener/search, GET /screener/presets, POST /screener/presets, DELETE /screener/presets/{id}, GET /screener/templates, GET /screener/export
    - Implement stock detail navigation endpoint: GET /stocks/{symbol}/detail (full fundamental + technical data)
    - _Requirements: 10.4, 10.6, 10.7, 11.4_

  - [x] 11.3 Write property tests for screener
    - **Property 14: Screener filter consistency** — all returned results satisfy every applied filter criterion
    - **Validates: Requirements 10.4, 10.5**

- [x] 12. Checkpoint — Stock universe, watchlists, and screener
  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. Zerodha Kite and Groww broker integrations
  - [x] 13.1 Implement Zerodha Kite broker
    - Create `src/ingestion/kite_broker.py` implementing existing `BrokerInterface` ABC
    - Implement Kite Connect API v3: OAuth2 login flow, access token storage
    - Implement `place_order()`: map internal order format to Kite params (exchange, tradingsymbol, transaction_type, quantity, price, trigger_price, order_type, product)
    - Support order types: MARKET, LIMIT, SL, SL-M
    - Implement order status polling every 1 second until terminal state (COMPLETE, CANCELLED, REJECTED)
    - Implement daily token refresh at 8:30 AM IST (Kite tokens expire daily)
    - Implement KiteTicker WebSocket for real-time market data as alternative source
    - Retry transient errors up to 2 times, log error codes and messages
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 15.6, 15.7, 15.8_

  - [x] 13.2 Implement Groww broker
    - Create `src/ingestion/groww_broker.py` implementing existing `BrokerInterface` ABC
    - Implement Groww trading API: OAuth2 auth flow, access token storage
    - Implement `place_order()`: map internal order to Groww API params, support MARKET, LIMIT, SL
    - Track order status until terminal state
    - Implement `get_holdings()` for portfolio reconciliation
    - Retry transient errors up to 2 times, log errors
    - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5, 16.6, 16.7_

  - [x] 13.3 Implement unified broker router with failover
    - Create `src/ingestion/broker_router.py` with `BrokerRouter` class
    - Maintain broker registry: {shoonya, angelone, kite, groww} → BrokerInterface instances
    - Implement `route_order()`: route to user's primary broker, auto-failover to backup on API unavailability
    - Implement `get_broker_status()`: connected, disconnected, token_expired
    - Implement common broker interface contract: place_order, cancel_order, get_order_status, get_positions, get_holdings
    - Log all broker API interactions with request/response for audit
    - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6, 17.7_

  - [x] 13.4 Create broker management API router
    - Create `backend-gateway/app/routers/broker_v2.py` with endpoints: POST /brokers/connect, DELETE /brokers/{name}/disconnect, GET /brokers/status, PUT /brokers/primary, PUT /brokers/backup
    - Display broker connection status on dashboard and settings
    - _Requirements: 17.2, 17.7_

  - [x] 13.5 Write property tests for broker routing
    - **Property 15: Broker failover** — when primary broker is unavailable, orders route to backup broker
    - **Property 16: Order format mapping** — internal order format maps correctly to each broker's API format and back
    - **Validates: Requirements 17.4, 15.5, 16.4**

- [x] 14. Checkpoint — Broker integrations
  - Ensure all tests pass, ask the user if questions arise.

- [x] 15. Real-time market data collection (NSE/BSE)
  - [x] 15.1 Implement NSE market data collector
    - Create `src/ingestion/market_data_collector.py` with `MarketDataCollector` class
    - Implement `connect_nse_feed()`: connect to NSE official data feeds for all actively traded securities
    - Collect per security: LTP, last traded qty, total volume, best bid/ask price+qty, OHLC, previous close
    - Publish price updates to Redis event bus within 50ms of receipt
    - Implement reconnection within 5 seconds on feed loss, fallback to broker WebSocket during outage
    - Collect pre-market session data (9:00-9:15 AM IST) including indicative opening prices
    - Collect post-market session data (3:30-4:00 PM IST) including closing prices
    - _Requirements: 25.1, 25.2, 25.4, 25.5, 25.6, 25.7_

  - [x] 15.2 Implement BSE market data collector
    - Implement `connect_bse_feed()`: connect to BSE official data feeds
    - Collect same data fields as NSE
    - Use NSE as primary for dual-listed, BSE as sole source for BSE-only securities
    - Implement `detect_price_discrepancy()`: log when NSE/BSE price difference >0.5% for dual-listed
    - Continue operating with NSE only if BSE feed unavailable
    - _Requirements: 26.1, 26.2, 26.3, 26.4, 26.5, 26.6_

  - [x] 15.3 Implement order book depth collection
    - Implement `collect_order_book()`: top 5 bid/ask levels for watchlist securities
    - Store in Redis: `depth:{symbol}` hash with bid_1..bid_5, ask_1..ask_5, bid_qty_1..bid_qty_5, ask_qty_1..ask_qty_5
    - _Requirements: 25.3_

  - [x] 15.4 Implement corporate actions collector
    - Implement `fetch_corporate_actions()`: dividends, splits, bonuses, rights, buybacks from NSE/BSE
    - Fetch exchange announcements: circuit breakers, trading halts, new listings
    - Store corporate action history: action type, ex-date, record date, details
    - Send notifications for corporate actions on watchlist securities
    - Fetch every 30 minutes during market hours and once at 7:00 PM IST after close
    - Update stock universe with adjusted prices after splits/bonuses
    - _Requirements: 27.1, 27.2, 27.3, 27.4, 27.5, 27.6_

  - [x] 15.5 Implement historical data expansion
    - Implement `backfill_historical()`: download daily OHLCV from NSE/BSE archives or Yahoo Finance
    - Store as Parquet on S3, partitioned by symbol and year
    - Maintain 10 years for large-cap, 5 years for mid/small-cap
    - Implement `adjust_for_corporate_actions()` and `revert_adjustments()` for price continuity
    - Provide API to query by symbol, date range, timeframe (daily/weekly/monthly)
    - _Requirements: 28.1, 28.2, 28.3, 28.4, 28.5, 28.6, 28.7_

  - [x] 15.6 Create market data API router
    - Create `backend-gateway/app/routers/market_data.py` with endpoints: GET /market/price/{symbol}, GET /market/depth/{symbol}, GET /market/corporate-actions, GET /market/historical/{symbol}
    - _Requirements: 25.2, 25.3, 27.4, 28.4_

  - [x] 15.7 Write property tests for corporate action adjustments
    - **Property 17: Corporate action round-trip** — applying adjustments then reverting produces original raw data for all securities with corporate actions
    - **Validates: Requirements 28.7**

  - [x] 15.8 Write property tests for price discrepancy detection
    - **Property 18: Price discrepancy detection** — dual-listed securities with >0.5% price difference between NSE and BSE are always flagged
    - **Validates: Requirements 26.5**

- [x] 16. Checkpoint — Market data collection
  - Ensure all tests pass, ask the user if questions arise.

- [x] 17. Gen AI chatbot service
  - [x] 17.1 Implement LLM client and RAG retrieval
    - Create `backend-gateway/app/services/chatbot_service.py` with `ChatbotService`, `LLMClient`, `ChartGenerator`
    - Implement `LLMClient.complete()`: wrapper for OpenAI GPT-4o-mini and Llama 3 APIs, target <5s for text
    - Implement `_retrieve_context()`: RAG query over user's trades, sentiment logs, signal history from PostgreSQL
    - Maintain conversation context per session (max 20 message exchanges), stored in Redis with 1-hour TTL
    - Support English and Hinglish input
    - Clearly state when insufficient data to answer (no speculative responses)
    - Only access authenticated user's own data
    - _Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6, 18.7, 19.5_

  - [x] 17.2 Implement trading data query handlers
    - Implement trade detail queries: entry/exit price, P&L, strategy, holding period
    - Implement performance queries: total P&L, win rate, avg profit, best/worst trades, Sharpe ratio for time periods
    - Implement signal explanation: strategy conditions, indicator values, bias state at entry time
    - Implement stock queries: current price, news sentiment, bias status, open positions, recent trades
    - Support time-range queries ("last week", "from January")
    - _Requirements: 19.1, 19.2, 19.3, 19.4, 19.6_

  - [x] 17.3 Implement chart generation
    - Implement `ChartGenerator` using matplotlib (backend-only, lightweight)
    - Generate equity curve SVG for performance-over-time queries
    - Generate daily P&L bar charts
    - Generate strategy comparison grouped bar charts
    - Generate candlestick charts with technical indicator overlays
    - Theme-aware (dark/light mode), consistent color scheme
    - Label axes, include legends, display data values
    - Target <10s for responses with charts
    - _Requirements: 20.1, 20.2, 20.3, 20.4, 20.5, 20.6, 20.7_

  - [x] 17.4 Implement data serialization and validation
    - Implement `serialize_query_results()`: trade query results to JSON for LLM context
    - Implement `deserialize_llm_response()`: LLM structured responses back to typed objects
    - Implement `validate_numeric_accuracy()`: verify LLM response numeric values match DB within 0.01 tolerance
    - Verify all trade IDs referenced in LLM responses exist in user's trade history
    - _Requirements: 21.1, 21.2, 21.4, 21.5_

  - [x] 17.5 Create chatbot API router
    - Create `backend-gateway/app/routers/chatbot.py` with endpoints: POST /chatbot/message, GET /chatbot/history, DELETE /chatbot/session
    - _Requirements: 18.1, 18.4_

  - [x] 17.6 Write property tests for serialization round-trip
    - **Property 19: Serialization round-trip** — serializing trade query results to JSON then deserializing back produces equivalent objects
    - **Validates: Requirements 21.3**

  - [x] 17.7 Write property tests for numeric accuracy validation
    - **Property 20: Numeric accuracy** — all numeric values in validated responses match source DB values within 0.01 tolerance
    - **Validates: Requirements 21.4**

- [x] 18. Checkpoint — Chatbot service
  - Ensure all tests pass, ask the user if questions arise.

- [x] 19. First-time user onboarding walkthrough (Web)
  - [x] 19.1 Implement walkthrough overlay component
    - Create `Lohi-TRADE Web App Design/src/components/onboarding/WalkthroughOverlay.tsx`
    - Implement 7-step guided walkthrough: Dashboard overview, Positions, Stock Screener, Watchlists, Broker connection, AI Chatbot, Kill Switch
    - Spotlight effect: CSS box-shadow overlay dimming rest of screen, highlight target element via `data-tour` selectors
    - Tooltip with title, description, animated pointer/arrow
    - Pure CSS animations only (opacity, transform, scale transitions) — no animation library dependencies
    - Navigation: Next, Back, Skip buttons with progress indicator (step X of Y)
    - Total payload <15KB gzipped (CSS + JS)
    - _Requirements: 33.1, 33.2, 33.3, 33.4, 33.5, 33.9, 33.10_

  - [x] 19.2 Wire onboarding to user lifecycle
    - Check `is_onboarded` flag on login — trigger walkthrough if false
    - Set `is_onboarded = true` on completion or skip
    - Add "Replay Tutorial" option in Settings page (resets flag)
    - Add `data-tour` attributes to all target UI elements across dashboard
    - Lazy-load WalkthroughOverlay via React.lazy + Suspense (zero bytes for returning users)
    - _Requirements: 33.1, 33.6, 33.7, 33.9_

  - [x] 19.3 Create onboarding backend endpoint
    - Add PUT /users/onboarded endpoint to update is_onboarded flag
    - _Requirements: 33.6, 33.7_

- [x] 20. Web app expansion — new pages and features
  - [x] 20.1 Add stock universe and screener pages to web app
    - Create StockUniversePage with sector tabs, search bar, paginated stock table
    - Create ScreenerPage with filter panel, sortable results table (50 rows/page), export CSV button
    - Create StockDetailPage with full fundamental + technical data, link from screener results
    - Display total matching count and applied filter summary at top of screener results
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6_

  - [x] 20.2 Add chatbot UI to web app
    - Create ChatbotPanel as a slide-out panel accessible from all pages
    - Implement conversational text interface with message input and response display
    - Render SVG/PNG chart images inline in chat responses
    - Support hover data values on charts
    - _Requirements: 18.1, 20.5, 20.7_

  - [x] 20.3 Add verification and bank account pages to web app
    - Create VerificationPage with PAN/KYC/DMAT step-by-step flow
    - Create BankAccountPage with account registration, deposit, withdrawal forms
    - Create FundTransactionsPage showing deposit/withdrawal history
    - _Requirements: 1-6 (UI for all verification and fund flows)_

  - [x] 20.4 Add broker management UI to web app
    - Create BrokerSettingsPage showing all 4 brokers (Shoonya, Angel One, Kite, Groww)
    - Display connection status per broker (connected, disconnected, token expired)
    - Allow setting primary and backup broker
    - OAuth connect/disconnect flows for each broker
    - _Requirements: 17.2, 17.7_

  - [x] 20.5 Update account creation and login page
    - Update LoginPage with "Continue with Google", "Continue with Apple", "Sign up with Email" buttons
    - Social login buttons prominently placed for faster onboarding
    - Full registration flow (landing to dashboard) under 60 seconds for social login
    - _Requirements: 32.8, 32.10_

- [x] 21. Checkpoint — Web app expansion
  - Ensure all tests pass, ask the user if questions arise.

- [x] 22. Web app performance optimization
  - [x] 22.1 Implement code splitting and bundle optimization
    - Add React.lazy + Suspense for all route-level page components
    - Configure Vite tree-shaking to eliminate unused code
    - Replace any heavy libraries: use date-fns (tree-shakeable) instead of moment.js, use lightweight-charts (~40KB) for charting
    - Import only individual Lucide icons actually used (no full icon set bundles)
    - Target <200KB gzipped initial bundle
    - _Requirements: 34.1, 34.2, 34.3, 34.4, 34.9, 34.10_

  - [x] 22.2 Implement backend performance optimizations
    - Configure asyncpg connection pooling: min 5, max 20 connections per worker
    - Configure Redis connection pooling: min 2, max 10 connections per worker
    - Add response compression middleware (gzip/brotli for >1KB responses)
    - Add HTTP caching headers (ETag, Cache-Control) for static data (stock universe, sector data)
    - Target <200ms p95 for read endpoints, <500ms p95 for write endpoints
    - _Requirements: 34.5, 34.6, 34.7, 34.12_

  - [x] 22.3 Optimize Docker images
    - Update Dockerfiles with multi-stage builds: python:3.12-slim for backend, node:20-alpine for frontend
    - Target <500MB per service image
    - _Requirements: 34.11_

- [x] 23. AWS infrastructure as code
  - [x] 23.1 Define VPC, networking, and security groups
    - Create AWS CDK (Python) project in `infra/` directory
    - Define VPC with public subnets (ALB) and private subnets (ECS tasks, databases)
    - Configure NAT Gateway for outbound internet from private subnets
    - Define security groups: ALB accepts HTTPS 443 only, ECS accepts from ALB only, Redis accepts from ECS only
    - _Requirements: 22.4, 22.5, 22.7_

  - [x] 23.2 Define ECS Fargate services
    - Define ECS cluster with Fargate launch type
    - Create task definitions: FastAPI gateway (auto-scale 2-10), Soldier, Commander, RMS+OMS, Market Data Collector, Verification Services, AI Chatbot
    - Configure ALB with health check endpoint /api/health
    - Configure ECR repositories for all service images
    - _Requirements: 22.1, 22.2, 22.3, 24.2_

  - [x] 23.3 Define data layer infrastructure
    - Define RDS PostgreSQL (db.t4g.medium) with Multi-AZ, 7-day automated backups, point-in-time recovery
    - Define ElastiCache Redis cluster as managed replacement for self-hosted Redis
    - Define S3 buckets: historical data (Parquet), KYC documents (SSE-S3 encryption), exports
    - Configure S3 lifecycle: transition >90 day data to Infrequent Access
    - Define AWS Secrets Manager for all sensitive credentials
    - _Requirements: 23.1, 23.2, 23.3, 23.4, 23.5, 23.6, 23.7_

  - [x] 23.4 Define CDN, DNS, and TLS
    - Define S3 bucket + CloudFront distribution for React web app static hosting
    - Define Route 53 hosted zone for platform domain
    - Define ACM certificates for ALB and CloudFront
    - _Requirements: 24.7, 24.8, 24.9_

  - [x] 23.5 Define monitoring and CI/CD
    - Configure CloudWatch log groups with 30-day retention for all ECS tasks
    - Define CloudWatch alarms: ECS CPU >80%, memory >80%, ALB 5xx >1%, RDS CPU >70%, Redis memory >80%
    - Configure AWS X-Ray for distributed tracing
    - Create GitHub Actions CI/CD pipeline: build → test → deploy-staging → deploy-production
    - _Requirements: 24.1, 24.3, 24.4, 24.5, 24.6_

- [x] 24. Checkpoint — AWS infrastructure
  - Ensure all tests pass, ask the user if questions arise.

- [x] 25. Mobile app — iOS (Swift/SwiftUI)
  - [x] 25.1 Set up iOS project and authentication
    - Create iOS project with Swift/SwiftUI, minimum iOS 16
    - Implement JWT-based auth communicating with existing FastAPI backend
    - Implement biometric auth (Face ID/Touch ID) as secondary login after initial JWT auth
    - Store JWT tokens in iOS Keychain
    - Implement automatic token refresh on expiry without re-login
    - Configure Firebase Cloud Messaging for push notifications (trade alerts, order updates, kill switch)
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6_

  - [x] 25.2 Implement iOS trading and portfolio features
    - Implement dashboard: current P&L, open positions, recent signals (identical to web)
    - Implement real-time price tickers via WebSocket (LTP, change amount, change%)
    - Implement position management: view and close individual positions
    - Implement order history: status, fill details, rejection reasons
    - Implement kill switch with confirmation dialog
    - Implement strategy performance analytics with equity curves and daily P&L charts
    - Implement watchlist operations (create, edit, delete, add/remove securities)
    - Implement stock screener with all filter params and sortable results
    - Implement notification center
    - _Requirements: 12.7, 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7, 13.8, 13.9_

  - [x] 25.3 Implement iOS offline capability and performance
    - Cache last known portfolio state locally (SQLite) for offline viewing
    - Display offline indicator with cached data and last-updated timestamp
    - Sync with server within 5 seconds on connectivity restore
    - Target <3s cold start to dashboard
    - Target <100MB RAM during normal operation
    - Target <5% battery per hour with real-time updates
    - Implement lazy screen loading and image caching for charts/avatars
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 34.8_

  - [x] 25.4 Implement iOS onboarding walkthrough
    - Implement 7-step walkthrough with SwiftUI animations (platform-appropriate)
    - Spotlight effect, tooltips, Next/Back/Skip navigation, progress indicator
    - _Requirements: 33.2, 33.3, 33.5, 33.8_

  - [x] 25.5 Implement iOS chatbot interface
    - Implement conversational text interface for AI chatbot
    - Render chart images inline, support tap for data values
    - _Requirements: 18.1, 20.7_

- [x] 26. Mobile app — Android (Kotlin/Jetpack Compose)
  - [x] 26.1 Set up Android project and authentication
    - Create Android project with Kotlin/Jetpack Compose, minimum API 26
    - Implement JWT-based auth communicating with existing FastAPI backend
    - Implement biometric auth (fingerprint/face unlock) as secondary login
    - Store JWT tokens in Android Keystore
    - Implement automatic token refresh on expiry
    - Configure Firebase Cloud Messaging for push notifications
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6_

  - [x] 26.2 Implement Android trading and portfolio features
    - Implement dashboard: current P&L, open positions, recent signals (identical to web)
    - Implement real-time price tickers via WebSocket
    - Implement position management, order history, kill switch with confirmation
    - Implement strategy analytics with charts
    - Implement watchlist operations and stock screener
    - Implement notification center
    - _Requirements: 12.7, 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7, 13.8, 13.9_

  - [x] 26.3 Implement Android offline capability and performance
    - Cache portfolio state locally (Room/SQLite) for offline viewing
    - Display offline indicator with cached data and last-updated timestamp
    - Sync within 5 seconds on connectivity restore
    - Target <3s cold start, <100MB RAM, <5% battery/hour
    - Implement lazy screen loading and image caching
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 34.8_

  - [x] 26.4 Implement Android onboarding walkthrough
    - Implement 7-step walkthrough with Jetpack Compose animations
    - Spotlight effect, tooltips, navigation, progress indicator
    - _Requirements: 33.2, 33.3, 33.5, 33.8_

  - [x] 26.5 Implement Android chatbot interface
    - Implement conversational text interface for AI chatbot
    - Render chart images inline, support tap for data values
    - _Requirements: 18.1, 20.7_

- [x] 27. Checkpoint — Mobile apps
  - Ensure all tests pass, ask the user if questions arise.

- [x] 28. End-to-end integration and final wiring
  - [x] 28.1 Wire all new backend services to FastAPI gateway
    - Register all new routers in main FastAPI app: auth_v2, verification, bank, stock_universe, watchlist, screener, market_data, chatbot, broker_v2
    - Ensure JWT middleware applies to all protected endpoints
    - Ensure RLS context (app.current_user_id) is set on every request
    - Wire push notification triggers: trade alerts → FCM, order updates → FCM, kill switch → FCM
    - _Requirements: 29.5, 12.6_

  - [x] 28.2 Wire market data collector to existing event bus
    - Connect MarketDataCollector output to existing Redis Streams (stream:ticks)
    - Ensure Soldier/Commander/RMS/OMS consume expanded market data seamlessly
    - Wire corporate action notifications to notification center
    - _Requirements: 25.4, 27.3_

  - [x] 28.3 Wire web app new pages and navigation
    - Add routes for all new pages: /stocks, /screener, /stocks/:symbol, /verification, /bank, /chatbot
    - Update sidebar navigation with new menu items
    - Wire chatbot panel toggle from all pages
    - Wire broker status display on dashboard and settings
    - _Requirements: 11.4, 17.7, 18.1_

  - [x] 28.4 Write integration tests for critical flows
    - Test: registration → PAN → KYC → DMAT → bank → deposit → trade flow
    - Test: screener filter → results → stock detail navigation
    - Test: chatbot query → RAG retrieval → LLM response → chart rendering
    - _Requirements: 1-6, 10-11, 18-21_

- [x] 29. Final checkpoint — Full platform expansion
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation after each major capability domain
- Property tests validate universal correctness properties from the design document
- The existing base system (Phases 1-13 in lohi-trade spec) is untouched — all tasks here are additive
- Mobile apps (tasks 25-26) can be developed in parallel with backend tasks
- AWS infrastructure (task 23) can be developed in parallel with application code
