# Requirements Document: LOHI-TRADE Platform Expansion

## Introduction

This document specifies requirements for the major platform expansion of the LOHI-TRADE algorithmic trading system. The existing system already provides a fully functional trading engine with broker integration (Shoonya, Angel One), technical analysis (The Soldier), sentiment analysis (The Commander), risk management, order management, backtesting, paper trading, Streamlit dashboard, Telegram bot, React frontend, and FastAPI backend gateway.

This expansion adds: account creation with social login (Google, Apple), first-time user onboarding walkthrough with guided animations, regulatory compliance (PAN/KYC verification, DMAT account linking), financial account management (bank account setup, deposits, withdrawals), comprehensive Indian stock universe with sector-based filtering and custom watchlists, a stock screener tool, native mobile applications (iOS and Android), additional broker platform integrations (Groww, Zerodha Kite), a Gen AI-powered personalized chatbot, AWS cloud deployment architecture, real-time market data collection from NSE/BSE official sources, and platform-wide performance optimization for lightweight and fast operation.

All features target the Indian stock market and comply with SEBI regulations. The expansion assumes open-source, cost-effective, and reliable technology choices.

## Glossary

- **PAN_Verification_Service**: Service that validates Permanent Account Number cards against NSDL/UTI databases for identity verification
- **KYC_Service**: Know Your Customer verification service that validates user identity documents per SEBI regulations
- **DMAT_Service**: Service managing Dematerialized account linking for electronic securities holding via CDSL/NSDL depositories
- **Bank_Account_Service**: Service handling bank account registration, UPI verification, deposit, and withdrawal operations
- **Stock_Universe_Service**: Service maintaining the complete catalog of NSE/BSE listed securities with metadata and sector classifications
- **Screener_Engine**: Filtering and ranking engine for stocks based on fundamental and technical parameters
- **Mobile_App**: Native iOS (Swift/SwiftUI) and Android (Kotlin/Jetpack Compose) applications with full feature parity to the web app
- **Broker_Integration_Service**: Service connecting to third-party broker platforms (Groww, Zerodha Kite) via their APIs for order routing
- **AI_Chatbot**: Gen AI-powered conversational assistant that answers user questions about their own trading data and performance
- **AWS_Infrastructure**: Cloud deployment architecture on Amazon Web Services for hosting, scaling, and managing the platform
- **Market_Data_Collector**: Service that collects real-time and historical market data from NSE/BSE official sources
- **PAN**: Permanent Account Number — 10-character alphanumeric identifier issued by Indian Income Tax Department
- **KYC**: Know Your Customer — identity verification process mandated by SEBI for securities trading
- **DMAT**: Dematerialized account — electronic account for holding securities, managed by CDSL or NSDL depositories
- **CDSL**: Central Depository Services Limited — Indian securities depository
- **NSDL**: National Securities Depository Limited — Indian securities depository
- **UPI**: Unified Payments Interface — real-time payment system by NPCI for bank transfers
- **SEBI**: Securities and Exchange Board of India — regulatory authority for securities markets
- **NSE**: National Stock Exchange of India
- **BSE**: Bombay Stock Exchange
- **ISIN**: International Securities Identification Number — unique 12-character code for a security
- **PE_Ratio**: Price-to-Earnings ratio — stock price divided by earnings per share
- **Market_Cap**: Market Capitalization — total market value of a company's outstanding shares
- **Dividend_Yield**: Annual dividend per share divided by stock price, expressed as percentage
- **Order_Book**: List of buy and sell orders for a security organized by price level
- **LLM**: Large Language Model — foundation model used by the AI_Chatbot for natural language understanding
- **RAG**: Retrieval-Augmented Generation — technique combining document retrieval with LLM generation for grounded responses
- **IFSC**: Indian Financial System Code — 11-character code identifying a bank branch
- **Onboarding_Service**: Guided walkthrough system that introduces first-time users to platform features via step-by-step animated tooltips and overlays
- **Account_Service**: User account creation and authentication service supporting email/password, Google OAuth, and Apple Sign-In
- **Social_Login**: Authentication via third-party identity providers (Google, Apple) using OAuth 2.0 / OpenID Connect
- **Walkthrough**: A sequence of animated tooltip overlays highlighting key UI elements to teach new users how to use the platform

## Requirements

### Requirement 1: PAN Card Verification

**User Story:** As a new user, I want to verify my PAN card on the platform, so that I can comply with Indian regulatory requirements for securities trading.

#### Acceptance Criteria

1. WHEN a user submits a PAN number, THE PAN_Verification_Service SHALL validate the format as exactly 10 alphanumeric characters matching the pattern [A-Z]{5}[0-9]{4}[A-Z]{1}
2. WHEN a valid PAN format is submitted, THE PAN_Verification_Service SHALL verify the PAN against the NSDL/UTI verification API within 10 seconds
3. WHEN the NSDL/UTI API confirms the PAN, THE PAN_Verification_Service SHALL store the verified PAN status, holder name, and verification timestamp in the user profile
4. WHEN the NSDL/UTI API rejects the PAN, THE PAN_Verification_Service SHALL return the specific rejection reason (invalid PAN, name mismatch, inactive PAN)
5. IF the NSDL/UTI API is unreachable, THEN THE PAN_Verification_Service SHALL retry up to 3 times with exponential backoff and notify the user of temporary unavailability
6. THE PAN_Verification_Service SHALL encrypt PAN numbers at rest using AES-256 encryption
7. THE PAN_Verification_Service SHALL mask PAN numbers in all API responses and logs, displaying only the first 2 and last 2 characters (e.g., AB******Z1)

### Requirement 2: KYC Verification

**User Story:** As a new user, I want to complete KYC verification, so that I can trade on the platform in compliance with SEBI regulations.

#### Acceptance Criteria

1. THE KYC_Service SHALL require PAN verification to be completed before initiating KYC verification
2. WHEN a user initiates KYC, THE KYC_Service SHALL collect: full name, date of birth, address, Aadhaar number (optional), and a photograph of a government-issued ID document
3. WHEN KYC documents are submitted, THE KYC_Service SHALL validate document image quality (minimum 300 DPI, file size between 100KB and 5MB, JPEG or PNG format)
4. WHEN documents pass quality checks, THE KYC_Service SHALL submit them to a KYC verification provider API (DigiLocker or KRA) for identity validation
5. WHEN the KYC provider confirms identity, THE KYC_Service SHALL update the user profile with KYC status as VERIFIED and store the verification reference number
6. WHEN the KYC provider rejects the submission, THE KYC_Service SHALL return the rejection reason and allow the user to resubmit corrected documents
7. IF the KYC provider API is unreachable, THEN THE KYC_Service SHALL queue the submission for retry and notify the user of the expected processing delay
8. THE KYC_Service SHALL encrypt all identity documents at rest using AES-256 encryption
9. THE KYC_Service SHALL delete uploaded identity document images within 30 days of successful verification, retaining only the verification status and reference number
10. THE KYC_Service SHALL support three KYC statuses: NOT_STARTED, PENDING, VERIFIED, and REJECTED

### Requirement 3: DMAT Account Linking

**User Story:** As a verified user, I want to link my DMAT account to the platform, so that I can hold securities electronically and enable delivery-based trading.

#### Acceptance Criteria

1. THE DMAT_Service SHALL require KYC status to be VERIFIED before allowing DMAT account linking
2. WHEN a user submits a DMAT account number, THE DMAT_Service SHALL validate the format (16-digit numeric for CDSL, IN followed by 14 alphanumeric characters for NSDL)
3. WHEN a valid DMAT number is submitted, THE DMAT_Service SHALL verify the account against the depository participant API (CDSL or NSDL) within 15 seconds
4. WHEN the depository confirms the account, THE DMAT_Service SHALL store the linked DMAT account ID, depository name (CDSL or NSDL), and DP name in the user profile
5. WHEN the depository rejects the account, THE DMAT_Service SHALL return the rejection reason (invalid account, PAN mismatch, account frozen)
6. THE DMAT_Service SHALL support linking a maximum of 3 DMAT accounts per user
7. WHEN a user requests to unlink a DMAT account, THE DMAT_Service SHALL verify that no open positions are held in that account before unlinking
8. THE DMAT_Service SHALL encrypt DMAT account numbers at rest using AES-256 encryption

### Requirement 4: Bank Account Registration and Verification

**User Story:** As a verified user, I want to add my bank account to the platform, so that I can deposit and withdraw funds for trading.

#### Acceptance Criteria

1. THE Bank_Account_Service SHALL require KYC status to be VERIFIED before allowing bank account registration
2. WHEN a user submits bank account details, THE Bank_Account_Service SHALL collect: account holder name, account number, IFSC code, bank name, and account type (savings or current)
3. WHEN bank details are submitted, THE Bank_Account_Service SHALL validate the IFSC code against the RBI IFSC directory
4. THE Bank_Account_Service SHALL verify bank account ownership by initiating a penny drop transaction (₹1 credit) via payment gateway and confirming the account holder name matches the KYC-verified name
5. WHEN penny drop verification succeeds, THE Bank_Account_Service SHALL mark the bank account as VERIFIED and store it in the user profile
6. WHEN penny drop verification fails, THE Bank_Account_Service SHALL return the failure reason and allow the user to correct details and retry
7. THE Bank_Account_Service SHALL support linking a maximum of 3 bank accounts per user
8. THE Bank_Account_Service SHALL designate one bank account as the primary account for withdrawals
9. THE Bank_Account_Service SHALL encrypt bank account numbers at rest using AES-256 encryption

### Requirement 5: Fund Deposit

**User Story:** As a trader, I want to deposit money into my trading account, so that I have capital available for placing trades.

#### Acceptance Criteria

1. THE Bank_Account_Service SHALL require at least one VERIFIED bank account before allowing deposits
2. WHEN a user initiates a deposit, THE Bank_Account_Service SHALL support payment via UPI, net banking, and NEFT/RTGS transfer methods
3. WHEN a UPI deposit is initiated, THE Bank_Account_Service SHALL generate a UPI payment link or QR code valid for 15 minutes
4. WHEN a deposit payment is confirmed by the payment gateway, THE Bank_Account_Service SHALL credit the user's trading balance within 30 seconds
5. THE Bank_Account_Service SHALL enforce a minimum deposit amount of ₹100 and a maximum single deposit of ₹10,00,000
6. THE Bank_Account_Service SHALL record every deposit transaction with: amount, payment method, transaction reference, timestamp, and status (INITIATED, PROCESSING, COMPLETED, FAILED)
7. IF a deposit payment fails, THEN THE Bank_Account_Service SHALL update the transaction status to FAILED and notify the user with the failure reason
8. THE Bank_Account_Service SHALL reconcile deposit records with payment gateway settlement reports daily at 6:00 PM IST

### Requirement 6: Fund Withdrawal

**User Story:** As a trader, I want to withdraw money from my trading account to my bank account, so that I can access my profits.

#### Acceptance Criteria

1. WHEN a user initiates a withdrawal, THE Bank_Account_Service SHALL verify that the requested amount does not exceed the available withdrawable balance (total balance minus margin blocked for open positions)
2. THE Bank_Account_Service SHALL process withdrawals only to VERIFIED bank accounts linked to the user profile
3. THE Bank_Account_Service SHALL enforce a minimum withdrawal amount of ₹100
4. WHEN a withdrawal is approved, THE Bank_Account_Service SHALL initiate a bank transfer via NEFT/IMPS to the designated bank account
5. THE Bank_Account_Service SHALL process withdrawal requests submitted before 4:00 PM IST on the same business day, and requests after 4:00 PM IST on the next business day
6. THE Bank_Account_Service SHALL record every withdrawal transaction with: amount, destination bank account, transaction reference, timestamp, and status (REQUESTED, PROCESSING, COMPLETED, FAILED)
7. IF a withdrawal transfer fails, THEN THE Bank_Account_Service SHALL reverse the debit to the user's trading balance and notify the user
8. THE Bank_Account_Service SHALL enforce a daily withdrawal limit of ₹25,00,000 per user


### Requirement 7: Stock Universe Management (NSE/BSE)

**User Story:** As a trader, I want access to all stocks listed on NSE and BSE, so that I can discover and trade any Indian security.

#### Acceptance Criteria

1. THE Stock_Universe_Service SHALL maintain a catalog of all actively traded securities on NSE and BSE (approximately 5000+ securities)
2. THE Stock_Universe_Service SHALL store for each security: symbol, ISIN, company name, exchange (NSE/BSE or both), sector, industry, market cap category (large-cap, mid-cap, small-cap), listing date, and face value
3. THE Stock_Universe_Service SHALL refresh the security catalog daily at 7:00 AM IST by fetching updated listings from NSE and BSE official data sources
4. WHEN a new security is listed on NSE or BSE, THE Stock_Universe_Service SHALL add it to the catalog within 24 hours of listing
5. WHEN a security is delisted or suspended, THE Stock_Universe_Service SHALL update its status to INACTIVE and prevent new orders for that security
6. THE Stock_Universe_Service SHALL provide a search API that returns matching securities within 200 milliseconds for queries by symbol, company name, or ISIN
7. THE Stock_Universe_Service SHALL expose a paginated listing API supporting filtering by exchange, sector, market cap category, and active status

### Requirement 8: Sector-Based Stock Classification and Filtering

**User Story:** As a trader, I want stocks organized by sector and industry, so that I can analyze and trade within specific market segments.

#### Acceptance Criteria

1. THE Stock_Universe_Service SHALL classify all securities into pre-defined sectors: Pharma, IT/Technology, AI/Deep Tech, Metals & Mining, Banking & Finance, FMCG, Energy, Automobile, Telecom, Real Estate, Infrastructure, Chemicals, Media & Entertainment, Insurance, and Miscellaneous
2. THE Stock_Universe_Service SHALL further classify securities into sub-industries within each sector (e.g., Banking → Private Banks, PSU Banks, NBFCs)
3. WHEN a user requests stocks by sector, THE Stock_Universe_Service SHALL return all active securities in that sector sorted by market capitalization in descending order
4. THE Stock_Universe_Service SHALL provide sector-level aggregate data: total market cap, number of stocks, top 5 gainers, and top 5 losers for the current trading day
5. THE Stock_Universe_Service SHALL allow filtering stocks within a sector by market cap range, PE ratio range, and dividend yield range
6. THE Stock_Universe_Service SHALL update sector classifications quarterly or when a company undergoes a significant business change

### Requirement 9: Custom Watchlist Management

**User Story:** As a trader, I want to create and manage custom watchlists, so that I can track specific stocks that interest me.

#### Acceptance Criteria

1. THE Stock_Universe_Service SHALL allow each user to create up to 20 custom watchlists
2. THE Stock_Universe_Service SHALL allow each watchlist to contain up to 100 securities
3. WHEN a user adds a security to a watchlist, THE Stock_Universe_Service SHALL validate that the security exists in the stock universe and is actively traded
4. THE Stock_Universe_Service SHALL support watchlist operations: create, rename, delete, add security, remove security, and reorder securities
5. WHEN a user views a watchlist, THE Stock_Universe_Service SHALL return current market data (LTP, change percentage, volume) for all securities in the watchlist within 500 milliseconds
6. THE Stock_Universe_Service SHALL persist watchlists in the database and synchronize across web and mobile clients
7. THE Stock_Universe_Service SHALL provide pre-built watchlists for Nifty 50, Nifty Bank, Nifty IT, Nifty Pharma, and Nifty Next 50 indices

### Requirement 10: Stock Screener — Parameter-Based Filtering

**User Story:** As a trader, I want a stock screener to filter stocks by fundamental and technical parameters, so that I can identify investment opportunities systematically.

#### Acceptance Criteria

1. THE Screener_Engine SHALL support filtering by the following fundamental parameters: PE ratio, PB ratio (price-to-book), market capitalization, dividend yield, EPS (earnings per share), ROE (return on equity), debt-to-equity ratio, revenue growth (1-year, 3-year), and profit growth (1-year, 3-year)
2. THE Screener_Engine SHALL support filtering by the following technical parameters: 52-week high/low proximity, RSI (14-period), moving average crossovers (50-day, 200-day), average daily volume, and price change percentage (1-day, 1-week, 1-month, 3-month, 6-month, 1-year, 3-year, 5-year)
3. THE Screener_Engine SHALL support filtering by return parameters: 1-year return, 3-year CAGR, and 5-year CAGR
4. WHEN a user applies screener filters, THE Screener_Engine SHALL return matching stocks sorted by the user-selected parameter within 2 seconds
5. THE Screener_Engine SHALL allow combining multiple filter parameters with AND logic
6. THE Screener_Engine SHALL allow users to save up to 10 custom screener presets with named filter combinations
7. THE Screener_Engine SHALL provide pre-built screener templates: "High Dividend Yield", "Undervalued Large Caps", "Momentum Stocks", "Low PE Growth Stocks", and "52-Week Breakout Candidates"
8. THE Screener_Engine SHALL update fundamental data from BSE/NSE corporate filings quarterly and technical data in real-time during market hours

### Requirement 11: Stock Screener — Results Display and Export

**User Story:** As a trader, I want screener results displayed in a sortable table with export capability, so that I can analyze filtered stocks efficiently.

#### Acceptance Criteria

1. WHEN screener results are returned, THE Screener_Engine SHALL display results in a paginated table with 50 rows per page
2. THE Screener_Engine SHALL allow sorting results by any displayed column in ascending or descending order
3. THE Screener_Engine SHALL display for each result: symbol, company name, sector, LTP, change percentage, market cap, PE ratio, and the specific parameters used in the filter
4. WHEN a user clicks on a stock in screener results, THE Screener_Engine SHALL navigate to the stock detail page showing full fundamental and technical data
5. THE Screener_Engine SHALL allow exporting screener results to CSV format with all displayed columns
6. THE Screener_Engine SHALL display the total count of matching stocks and the applied filter summary at the top of results


### Requirement 12: Mobile App — Core Architecture and Authentication

**User Story:** As a mobile user, I want a native app on my iPhone and Android device, so that I can trade and monitor my portfolio on the go.

#### Acceptance Criteria

1. THE Mobile_App SHALL be built as native applications: iOS using Swift/SwiftUI (minimum iOS 16) and Android using Kotlin/Jetpack Compose (minimum Android API 26)
2. THE Mobile_App SHALL authenticate users using the same JWT-based authentication as the web app, communicating with the existing FastAPI backend gateway
3. THE Mobile_App SHALL support biometric authentication (Face ID/Touch ID on iOS, fingerprint/face unlock on Android) as a secondary login method after initial JWT authentication
4. THE Mobile_App SHALL store JWT tokens securely using iOS Keychain and Android Keystore respectively
5. WHEN the JWT token expires, THE Mobile_App SHALL automatically refresh the token using the refresh endpoint without requiring the user to re-login
6. THE Mobile_App SHALL support push notifications via Firebase Cloud Messaging for trade alerts, order status updates, and kill switch activations
7. THE Mobile_App SHALL maintain a persistent WebSocket connection to the backend for real-time price updates, reconnecting automatically on network changes

### Requirement 13: Mobile App — Trading and Portfolio Features

**User Story:** As a mobile trader, I want full trading capabilities on my phone, so that I can manage positions and execute trades from anywhere.

#### Acceptance Criteria

1. THE Mobile_App SHALL display the dashboard with current P&L, open positions, and recent signals identical to the web app
2. THE Mobile_App SHALL display real-time price tickers with LTP, change amount, and change percentage updated via WebSocket
3. THE Mobile_App SHALL allow viewing and managing open positions with options to close individual positions
4. THE Mobile_App SHALL allow viewing order history with status, fill details, and rejection reasons
5. THE Mobile_App SHALL allow activating and deactivating the kill switch with a confirmation dialog
6. THE Mobile_App SHALL display strategy performance analytics with equity curves and daily P&L charts
7. THE Mobile_App SHALL support all watchlist operations (create, edit, delete, add/remove securities)
8. THE Mobile_App SHALL support the stock screener with all filter parameters and sortable results
9. THE Mobile_App SHALL display the notification center with trade, system, and alert notifications

### Requirement 14: Mobile App — Offline Capability and Performance

**User Story:** As a mobile user, I want the app to work reliably even with intermittent connectivity, so that I can view my portfolio data at all times.

#### Acceptance Criteria

1. THE Mobile_App SHALL cache the last known portfolio state (positions, orders, P&L) locally for offline viewing
2. WHEN network connectivity is lost, THE Mobile_App SHALL display a clear offline indicator and show cached data with the last-updated timestamp
3. WHEN network connectivity is restored, THE Mobile_App SHALL synchronize local state with the server within 5 seconds
4. THE Mobile_App SHALL launch to the dashboard screen within 3 seconds on a cold start
5. THE Mobile_App SHALL consume less than 100MB of RAM during normal operation
6. THE Mobile_App SHALL consume less than 5% battery per hour during active use with real-time updates enabled

### Requirement 15: Zerodha Kite Broker Integration

**User Story:** As a Zerodha user, I want to connect my Kite account to LOHI-TRADE, so that I can execute algorithmic trades through my existing Zerodha account.

#### Acceptance Criteria

1. THE Broker_Integration_Service SHALL implement the Zerodha Kite Connect API v3 for authentication, order placement, and market data
2. WHEN a user connects their Zerodha account, THE Broker_Integration_Service SHALL initiate the Kite Connect OAuth2 login flow and store the access token securely
3. THE Broker_Integration_Service SHALL refresh the Zerodha access token daily at 8:30 AM IST before market open, as Kite tokens expire daily
4. THE Broker_Integration_Service SHALL support order types: MARKET, LIMIT, SL (stop-loss), and SL-M (stop-loss market) via Kite API
5. THE Broker_Integration_Service SHALL map LOHI-TRADE internal order format to Kite API order parameters (exchange, tradingsymbol, transaction_type, quantity, price, trigger_price, order_type, product)
6. WHEN an order is placed via Kite API, THE Broker_Integration_Service SHALL poll order status every 1 second until the order reaches a terminal state (COMPLETE, CANCELLED, REJECTED)
7. THE Broker_Integration_Service SHALL fetch real-time market data via Kite WebSocket (KiteTicker) as an alternative data source
8. IF the Kite API returns an error, THEN THE Broker_Integration_Service SHALL log the error code and message, and retry transient errors up to 2 times

### Requirement 16: Groww Broker Integration

**User Story:** As a Groww user, I want to connect my Groww account to LOHI-TRADE, so that I can execute trades through my existing Groww account.

#### Acceptance Criteria

1. THE Broker_Integration_Service SHALL implement the Groww trading API for authentication, order placement, and portfolio retrieval
2. WHEN a user connects their Groww account, THE Broker_Integration_Service SHALL authenticate via Groww's OAuth2 flow and store the access token securely
3. THE Broker_Integration_Service SHALL support order types available on Groww: MARKET, LIMIT, and SL (stop-loss)
4. THE Broker_Integration_Service SHALL map LOHI-TRADE internal order format to Groww API order parameters
5. WHEN an order is placed via Groww API, THE Broker_Integration_Service SHALL track order status until terminal state
6. IF the Groww API returns an error, THEN THE Broker_Integration_Service SHALL log the error and retry transient errors up to 2 times
7. THE Broker_Integration_Service SHALL fetch portfolio holdings and positions from Groww for reconciliation with LOHI-TRADE records

### Requirement 17: Unified Broker Selection and Routing

**User Story:** As a trader with multiple broker accounts, I want to select which broker to use for trading, so that I can route orders through my preferred platform.

#### Acceptance Criteria

1. THE Broker_Integration_Service SHALL maintain a broker registry supporting: Shoonya, Angel One, Zerodha Kite, and Groww
2. THE Broker_Integration_Service SHALL allow the user to set a primary broker and an optional backup broker in their profile settings
3. WHEN an order is submitted, THE Broker_Integration_Service SHALL route the order to the user's selected primary broker
4. IF the primary broker API is unavailable, THEN THE Broker_Integration_Service SHALL automatically failover to the backup broker and notify the user
5. THE Broker_Integration_Service SHALL implement a common broker interface so that all broker-specific implementations conform to the same contract (place_order, cancel_order, get_order_status, get_positions, get_holdings)
6. THE Broker_Integration_Service SHALL log all broker API interactions with request/response details for audit purposes
7. THE Broker_Integration_Service SHALL display broker connection status (connected, disconnected, token expired) on the dashboard and settings page


### Requirement 18: Gen AI Chatbot — Conversational Interface

**User Story:** As a trader, I want a chatbot that explains my trades and performance in natural language, so that I can understand my trading activity without analyzing raw data.

#### Acceptance Criteria

1. THE AI_Chatbot SHALL provide a conversational text interface accessible from the web app and mobile app
2. THE AI_Chatbot SHALL use a Large Language Model (LLM) via API (OpenAI GPT-4o-mini or equivalent open-source model such as Llama 3) for natural language understanding and response generation
3. WHEN a user sends a message, THE AI_Chatbot SHALL respond within 5 seconds for text-only responses and within 10 seconds for responses that include charts
4. THE AI_Chatbot SHALL maintain conversation context for the current session (up to 20 message exchanges)
5. THE AI_Chatbot SHALL only access and reference the authenticated user's own trading data; the AI_Chatbot SHALL NOT access or reveal data belonging to other users
6. THE AI_Chatbot SHALL clearly state when it does not have sufficient data to answer a question rather than generating speculative responses
7. THE AI_Chatbot SHALL support both English and Hinglish (Hindi-English mixed) input from users

### Requirement 19: Gen AI Chatbot — Trading Data Queries

**User Story:** As a trader, I want to ask the chatbot questions about my trades, so that I can get quick insights without navigating through multiple screens.

#### Acceptance Criteria

1. WHEN a user asks about a specific trade, THE AI_Chatbot SHALL retrieve the trade details (entry/exit price, P&L, strategy, holding period) from the database and present them in a readable format
2. WHEN a user asks about overall performance, THE AI_Chatbot SHALL calculate and present: total P&L, win rate, average profit per trade, best and worst trades, and Sharpe ratio for the requested time period
3. WHEN a user asks "why was this trade taken?", THE AI_Chatbot SHALL explain the strategy conditions that triggered the signal (indicator values, bias state) at the time of entry
4. WHEN a user asks about a specific stock, THE AI_Chatbot SHALL retrieve current price, recent news sentiment, bias status, and any open positions or recent trades for that stock
5. THE AI_Chatbot SHALL use RAG (Retrieval-Augmented Generation) to query the user's trade database, sentiment logs, and signal history before generating responses
6. THE AI_Chatbot SHALL support time-range queries such as "How did I perform last week?" or "Show my trades from January"

### Requirement 20: Gen AI Chatbot — Visual Responses with Charts

**User Story:** As a trader, I want the chatbot to show charts and graphs in its responses, so that I can visually understand my trading performance.

#### Acceptance Criteria

1. WHEN a user asks about performance over time, THE AI_Chatbot SHALL generate and display an equity curve chart for the requested period
2. WHEN a user asks about daily P&L, THE AI_Chatbot SHALL generate and display a bar chart showing daily profit and loss
3. WHEN a user asks about strategy comparison, THE AI_Chatbot SHALL generate and display a grouped bar chart comparing strategy-level metrics (P&L, win rate, trade count)
4. WHEN a user asks about a stock's price history, THE AI_Chatbot SHALL generate and display a candlestick chart with the relevant technical indicators overlaid
5. THE AI_Chatbot SHALL generate charts as SVG or PNG images embedded in the chat response
6. THE AI_Chatbot SHALL use a consistent color scheme matching the platform's theme (dark/light mode aware)
7. THE AI_Chatbot SHALL label all chart axes, include legends, and display data values on hover (web) or tap (mobile)

### Requirement 21: Gen AI Chatbot — Data Serialization and Round-Trip Integrity

**User Story:** As a developer, I want chatbot query results to be serialized and deserialized consistently, so that data integrity is maintained between the LLM context and the database.

#### Acceptance Criteria

1. THE AI_Chatbot SHALL serialize trade query results to JSON format before passing them to the LLM context
2. THE AI_Chatbot SHALL deserialize LLM-structured responses back into typed objects for chart generation
3. FOR ALL valid trade query results, serializing to JSON then deserializing back SHALL produce an equivalent object (round-trip property)
4. THE AI_Chatbot SHALL validate that all numeric values (prices, P&L, percentages) in LLM responses match the source database values within a tolerance of 0.01
5. WHEN the LLM returns a response referencing trade IDs, THE AI_Chatbot SHALL verify that all referenced trade IDs exist in the user's trade history

### Requirement 22: AWS Infrastructure — Compute and Networking

**User Story:** As a platform operator, I want the system deployed on AWS, so that it can scale reliably and serve multiple users.

#### Acceptance Criteria

1. THE AWS_Infrastructure SHALL deploy the FastAPI backend gateway on Amazon ECS Fargate with auto-scaling (minimum 2 tasks, maximum 10 tasks)
2. THE AWS_Infrastructure SHALL deploy the trading engine (Soldier, Commander, RMS, OMS) on Amazon ECS Fargate with dedicated task definitions per component
3. THE AWS_Infrastructure SHALL use an Application Load Balancer (ALB) to distribute traffic across backend gateway tasks with health check endpoint /api/health
4. THE AWS_Infrastructure SHALL deploy all services within a VPC with public subnets for ALB and private subnets for ECS tasks and databases
5. THE AWS_Infrastructure SHALL use AWS NAT Gateway for outbound internet access from private subnets (broker API calls, news feeds)
6. THE AWS_Infrastructure SHALL use Amazon ElastiCache (Redis) as a managed replacement for the self-hosted Redis container
7. THE AWS_Infrastructure SHALL use security groups restricting inbound traffic: ALB accepts HTTPS (443) only, ECS tasks accept traffic only from ALB, Redis accepts traffic only from ECS tasks

### Requirement 23: AWS Infrastructure — Data Storage and Persistence

**User Story:** As a platform operator, I want managed database services on AWS, so that trading data is durable, backed up, and performant.

#### Acceptance Criteria

1. THE AWS_Infrastructure SHALL use Amazon RDS PostgreSQL (db.t4g.medium) as the primary operational database, replacing SQLite for multi-user support
2. THE AWS_Infrastructure SHALL configure RDS with Multi-AZ deployment for high availability
3. THE AWS_Infrastructure SHALL enable automated RDS backups with 7-day retention and point-in-time recovery
4. THE AWS_Infrastructure SHALL use Amazon S3 for storing historical market data in Parquet format, replacing local DuckDB files
5. THE AWS_Infrastructure SHALL use Amazon S3 for storing KYC documents with server-side encryption (SSE-S3)
6. THE AWS_Infrastructure SHALL use Amazon S3 lifecycle policies to transition historical data older than 90 days to S3 Infrequent Access storage class
7. THE AWS_Infrastructure SHALL use AWS Secrets Manager to store all sensitive credentials (broker API keys, database passwords, JWT secrets)

### Requirement 24: AWS Infrastructure — Deployment, Monitoring, and CI/CD

**User Story:** As a DevOps engineer, I want automated deployment pipelines and monitoring, so that I can deploy updates safely and detect issues quickly.

#### Acceptance Criteria

1. THE AWS_Infrastructure SHALL use AWS CDK (Python) or Terraform for defining all infrastructure as code
2. THE AWS_Infrastructure SHALL use Amazon ECR for storing Docker container images for all services
3. THE AWS_Infrastructure SHALL use GitHub Actions or AWS CodePipeline for CI/CD with stages: build, test, deploy-staging, deploy-production
4. THE AWS_Infrastructure SHALL use Amazon CloudWatch for centralized logging from all ECS tasks with 30-day log retention
5. THE AWS_Infrastructure SHALL configure CloudWatch alarms for: ECS task CPU > 80%, ECS task memory > 80%, ALB 5xx error rate > 1%, RDS CPU > 70%, and Redis memory > 80%
6. THE AWS_Infrastructure SHALL use AWS X-Ray for distributed tracing across backend gateway and trading engine components
7. THE AWS_Infrastructure SHALL deploy the React web app as a static site on Amazon S3 with CloudFront CDN distribution
8. THE AWS_Infrastructure SHALL use Amazon Route 53 for DNS management with the platform's domain name
9. THE AWS_Infrastructure SHALL use AWS Certificate Manager for TLS certificates on ALB and CloudFront


### Requirement 25: Real-Time Market Data Collection from NSE

**User Story:** As a trader, I want real-time market data from NSE, so that I have accurate and timely information for all listed securities.

#### Acceptance Criteria

1. THE Market_Data_Collector SHALL connect to NSE official data feeds for real-time price updates of all actively traded securities
2. THE Market_Data_Collector SHALL collect for each security: last traded price (LTP), last traded quantity, total traded volume, best bid price and quantity, best ask price and quantity, open, high, low, close, and previous close
3. THE Market_Data_Collector SHALL collect full order book depth (top 5 bid/ask levels) for securities in the user's active watchlists
4. THE Market_Data_Collector SHALL publish price updates to the Event_Bus within 50 milliseconds of receipt
5. WHEN the NSE data feed connection is lost, THE Market_Data_Collector SHALL attempt reconnection within 5 seconds and fall back to broker WebSocket data during the outage
6. THE Market_Data_Collector SHALL collect pre-market session data (9:00 AM - 9:15 AM IST) including indicative opening prices
7. THE Market_Data_Collector SHALL collect post-market session data (3:30 PM - 4:00 PM IST) including closing prices

### Requirement 26: Real-Time Market Data Collection from BSE

**User Story:** As a trader, I want real-time market data from BSE, so that I can trade securities listed exclusively on BSE and compare prices across exchanges.

#### Acceptance Criteria

1. THE Market_Data_Collector SHALL connect to BSE official data feeds for real-time price updates
2. THE Market_Data_Collector SHALL collect the same data fields from BSE as from NSE (LTP, volume, bid/ask, OHLC)
3. WHEN a security is listed on both NSE and BSE, THE Market_Data_Collector SHALL use NSE data as the primary source and BSE data for cross-validation
4. WHEN a security is listed only on BSE, THE Market_Data_Collector SHALL use BSE data as the sole source
5. THE Market_Data_Collector SHALL detect price discrepancies greater than 0.5% between NSE and BSE for dual-listed securities and log them for analysis
6. IF the BSE data feed is unavailable, THEN THE Market_Data_Collector SHALL continue operating with NSE data only and log the BSE outage

### Requirement 27: Market Data — Corporate Actions and Announcements

**User Story:** As a trader, I want to receive corporate action updates and exchange announcements, so that I can factor in events like dividends, splits, and bonuses into my trading decisions.

#### Acceptance Criteria

1. THE Market_Data_Collector SHALL fetch corporate action data from NSE and BSE: dividends, stock splits, bonus issues, rights issues, and buybacks
2. THE Market_Data_Collector SHALL fetch exchange announcements: circuit breaker activations, trading halts, and new listings
3. WHEN a corporate action is announced for a security in the user's watchlist, THE Market_Data_Collector SHALL send a notification to the user via the notification center and push notification (mobile)
4. THE Market_Data_Collector SHALL store corporate action history for all securities with: action type, ex-date, record date, and details
5. THE Market_Data_Collector SHALL update the stock universe with adjusted prices after stock splits and bonus issues
6. THE Market_Data_Collector SHALL fetch corporate action data every 30 minutes during market hours and once at 7:00 PM IST after market close

### Requirement 28: Market Data — Historical Data Expansion

**User Story:** As a trader, I want comprehensive historical data for all Indian securities, so that I can analyze long-term trends and backtest strategies on a wider universe.

#### Acceptance Criteria

1. THE Market_Data_Collector SHALL download and store daily OHLCV data for all NSE and BSE actively traded securities (not just Nifty 50)
2. THE Market_Data_Collector SHALL maintain at least 10 years of daily historical data for large-cap securities and 5 years for mid-cap and small-cap securities
3. THE Market_Data_Collector SHALL store historical data in Parquet format on Amazon S3, partitioned by symbol and year
4. THE Market_Data_Collector SHALL provide an API to query historical data by symbol, date range, and timeframe (daily, weekly, monthly)
5. WHEN historical data is missing for a security, THE Market_Data_Collector SHALL backfill from available sources (NSE archives, BSE archives, Yahoo Finance)
6. THE Market_Data_Collector SHALL adjust historical prices for corporate actions (splits, bonuses) to maintain data continuity
7. FOR ALL securities with corporate action adjustments, fetching raw data then applying adjustments then reverting adjustments SHALL produce the original raw data (round-trip property)

### Requirement 29: Multi-User Support and Authorization

**User Story:** As a platform operator, I want the system to support multiple users with role-based access, so that each user has a secure and isolated trading experience.

#### Acceptance Criteria

1. THE System SHALL support user registration with email, phone number, and password
2. THE System SHALL enforce password requirements: minimum 8 characters, at least one uppercase letter, one lowercase letter, one digit, and one special character
3. THE System SHALL implement role-based access control with roles: ADMIN (full system access), TRADER (trading and portfolio access), and VIEWER (read-only portfolio access)
4. THE System SHALL isolate all user data (trades, positions, orders, watchlists, chatbot conversations) by user ID with row-level security in PostgreSQL
5. WHEN a user accesses any API endpoint, THE System SHALL verify the JWT token and enforce that the user can only access their own data
6. THE System SHALL support account deactivation by ADMIN users, which prevents login and halts all active trading for the deactivated user
7. THE System SHALL log all authentication events (login, logout, failed attempts, token refresh) for security audit

### Requirement 30: API Rate Limiting and Security

**User Story:** As a platform operator, I want API rate limiting and security controls, so that the platform is protected from abuse and unauthorized access.

#### Acceptance Criteria

1. THE System SHALL enforce API rate limits: 100 requests per minute per user for read endpoints and 30 requests per minute per user for write endpoints
2. WHEN a user exceeds the rate limit, THE System SHALL return HTTP 429 (Too Many Requests) with a Retry-After header
3. THE System SHALL enforce HTTPS for all API communication using TLS 1.2 or higher
4. THE System SHALL implement CORS (Cross-Origin Resource Sharing) allowing only the platform's web domain and mobile app origins
5. THE System SHALL sanitize all user inputs to prevent SQL injection, XSS, and command injection attacks
6. THE System SHALL implement request signing for all broker API calls to prevent tampering
7. THE System SHALL log all API requests with: user ID, endpoint, method, response status, and response time for monitoring and audit

### Requirement 31: Data Migration from SQLite to PostgreSQL

**User Story:** As a platform operator, I want existing trading data migrated from SQLite to PostgreSQL, so that the platform can support multiple concurrent users.

#### Acceptance Criteria

1. THE System SHALL provide a migration script that transfers all data from SQLite tables (trades, orders, positions, sentiment_log, bias_log, audit_log) to PostgreSQL
2. THE System SHALL validate data integrity after migration by comparing row counts and checksums between SQLite and PostgreSQL for each table
3. THE System SHALL add user_id columns to all migrated tables and assign existing data to the initial admin user
4. THE System SHALL create PostgreSQL indexes on frequently queried columns: user_id, symbol, timestamp, and status
5. FOR ALL tables migrated, exporting from SQLite then importing to PostgreSQL then exporting from PostgreSQL SHALL produce equivalent data sets (round-trip property)
6. THE System SHALL support running the migration script idempotently without duplicating data on re-runs

### Requirement 32: Account Creation and Social Login

**User Story:** As a new user, I want to create an account using my email or social login (Google, Apple), so that I can get started on the platform quickly without a lengthy registration process.

#### Acceptance Criteria

1. THE Account_Service SHALL support account creation via email and password with mandatory email verification (OTP or magic link valid for 15 minutes)
2. THE Account_Service SHALL support Google OAuth 2.0 login using the Google Identity Services library, extracting email, name, and profile picture from the Google ID token
3. THE Account_Service SHALL support Apple Sign-In using the Sign in with Apple REST API, handling both email-sharing and email-hidden scenarios
4. WHEN a user signs up via social login, THE Account_Service SHALL create a user profile using the provider's verified email and name, without requiring a separate password
5. WHEN a user signs up via social login and an account with the same email already exists, THE Account_Service SHALL link the social provider to the existing account rather than creating a duplicate
6. THE Account_Service SHALL issue a JWT access token (15-minute expiry) and a refresh token (30-day expiry) upon successful login via any method
7. THE Account_Service SHALL store only the social provider ID and provider type in the user profile; THE Account_Service SHALL NOT store social login access tokens or passwords in plain text
8. THE Account_Service SHALL display the account creation page with clear options: "Continue with Google", "Continue with Apple", and "Sign up with Email" — with social login buttons prominently placed for faster onboarding
9. THE Account_Service SHALL collect phone number (Indian mobile, 10 digits) during registration for OTP-based two-factor authentication
10. THE Account_Service SHALL complete the full registration flow (from landing page to dashboard) in under 60 seconds for social login users

### Requirement 33: First-Time User Onboarding Walkthrough

**User Story:** As a first-time user, I want an animated guided walkthrough when I log in for the first time, so that I can quickly understand how to use the platform's key features.

#### Acceptance Criteria

1. WHEN a user logs in for the first time (is_onboarded flag is false), THE Onboarding_Service SHALL display an animated step-by-step walkthrough overlay on the dashboard
2. THE Onboarding_Service SHALL guide the user through the following steps in sequence: (a) Dashboard overview and P&L cards, (b) How to view and manage positions, (c) How to use the stock screener, (d) How to create and manage watchlists, (e) How to connect a broker account, (f) How to use the AI chatbot, (g) How to activate the kill switch
3. EACH walkthrough step SHALL highlight the relevant UI element with a spotlight effect (dimming the rest of the screen) and display a tooltip with a short description and an animated pointer or arrow
4. THE Onboarding_Service SHALL use lightweight CSS animations (opacity, transform, scale transitions) for all walkthrough effects — no heavy animation libraries or GIF/video assets
5. THE Onboarding_Service SHALL allow the user to navigate between steps using "Next", "Back", and "Skip" buttons, and a progress indicator showing current step out of total steps
6. WHEN the user completes or skips the walkthrough, THE Onboarding_Service SHALL set the is_onboarded flag to true in the user profile and not show the walkthrough again on subsequent logins
7. THE Onboarding_Service SHALL provide a "Replay Tutorial" option in the Settings page that resets the is_onboarded flag and replays the walkthrough on next navigation to the dashboard
8. THE Onboarding_Service SHALL render the walkthrough on both web (React) and mobile (SwiftUI/Jetpack Compose) with platform-appropriate animations
9. THE Onboarding_Service SHALL load the entire walkthrough component lazily (code-split) so that it adds zero bytes to the initial bundle for returning users
10. THE total walkthrough animation payload SHALL be less than 15KB gzipped (CSS + JS), with no external animation library dependencies

### Requirement 34: Platform-Wide Performance and Lightweight Code Optimization

**User Story:** As a user, I want the platform to be fast and responsive, so that I can trade efficiently without waiting for pages to load or actions to complete.

#### Acceptance Criteria

1. THE web app SHALL achieve a Lighthouse Performance score of 90 or above on mobile and desktop
2. THE web app initial bundle size (JavaScript + CSS) SHALL be less than 200KB gzipped, using code splitting and lazy loading for all non-critical routes
3. THE web app SHALL implement tree-shaking to eliminate unused code from all dependencies
4. THE web app SHALL lazy-load all page components (React.lazy + Suspense) so that only the active route's code is loaded
5. THE backend API SHALL respond to all read endpoints within 200 milliseconds (p95) and all write endpoints within 500 milliseconds (p95) under normal load (100 concurrent users)
6. THE backend SHALL use connection pooling for PostgreSQL (minimum 5, maximum 20 connections per worker) and Redis (minimum 2, maximum 10 connections per worker)
7. THE backend SHALL implement response compression (gzip/brotli) for all API responses larger than 1KB
8. THE Mobile_App SHALL use lazy loading for non-visible screens and image caching for all chart and avatar assets
9. THE System SHALL prefer lightweight libraries over heavy alternatives: use date-fns instead of moment.js, use lightweight chart libraries (lightweight-charts by TradingView, ~40KB) instead of heavy charting suites
10. THE System SHALL avoid bundling unused icon sets — only import individual icons actually used in the UI
11. THE Docker container images SHALL use multi-stage builds with slim base images (python:3.12-slim, node:20-alpine) to minimize image size below 500MB per service
12. THE System SHALL implement HTTP caching headers (ETag, Cache-Control) for static assets and infrequently changing API responses (stock universe, sector data)
