# Multi-Country Market Support

## Overview

Lohi-Trade supports trading in multiple countries through a pluggable market profile system. During setup, the user selects their country, which configures:

- Trading hours and timezone
- Currency and number formatting
- Available brokers
- Benchmark index (for volatility guard)
- Tax rules and charge estimation
- News sources for sentiment analysis
- Default symbol watchlist
- Exchange-specific settings

## Supported Markets

| Country | Exchange | Currency | Benchmark | Brokers |
|---------|----------|----------|-----------|---------|
| India | NSE/BSE | INR (₹) | Nifty 50 | Shoonya, Angel One, Zerodha, Groww |
| United States | NYSE/NASDAQ | USD ($) | S&P 500 | Alpaca, Interactive Brokers, Tradier, Schwab |
| United Kingdom | LSE | GBP (£) | FTSE 100 | Interactive Brokers, IG, Saxo |
| Australia | ASX | AUD (A$) | S&P/ASX 200 | Interactive Brokers, Stake |
| Canada | TSX | CAD (C$) | S&P/TSX Composite | Interactive Brokers, Questrade, Wealthsimple |
| Germany | XETRA | EUR (€) | DAX 40 | Interactive Brokers, Scalable Capital |
| Japan | JPX | JPY (¥) | Nikkei 225 | Interactive Brokers, SBI Securities |
| Singapore | SGX | SGD (S$) | Straits Times Index | Interactive Brokers, Tiger Brokers, Moomoo |

## Setup Flow

### Step 1: Country Selection (NEW — first screen)

```
GET  /api/market/countries     → List available countries
POST /api/market/select        → Select country (persists to config/market.yaml)
GET  /api/market/status        → Check if market is configured
```

### Step 2: Broker Selection (filtered by country)

```
GET  /api/market/brokers       → Get brokers for selected country
```

### Step 3: Credentials (existing flow, now country-aware)

The setup wizard shows only brokers available in the selected country.

## Tax Profile System

### Pre-built Profiles

Each country ships with a manually verified tax profile including:
- Transaction taxes (STT, stamp duty, exchange fees, etc.)
- Capital gains rates (short-term and long-term)
- Holding period thresholds
- Wash sale / superficial loss rules
- Dividend tax rates

### AI-Powered Tax Refresh

Users can optionally refresh tax rules using an LLM API call:

```
POST /api/market/tax/generate/{country_code}  → Generate via AI
POST /api/market/tax/refresh                  → Refresh existing profile
POST /api/market/tax/confirm                  → Confirm after review
```

The AI generates a Pydantic-validated `TaxProfile` that the user must review and confirm before it's applied. This ensures:
1. Tax rules stay current (budget changes, rate updates)
2. Users maintain control over what rules are applied
3. The system never silently applies incorrect tax calculations

### Charge Estimation

```
POST /api/market/estimate-charges  → Estimate charges for a trade
```

Used by the order ticket to show estimated transaction costs before submission.

## Architecture

```
src/markets/
├── __init__.py                 # Public API
├── market_profile.py           # Pydantic models (Country, Exchange, TaxProfile, etc.)
├── market_registry.py          # Registry + persistence (config/market.yaml)
├── tax_engine.py               # Charge calculation engine
├── tax_profile_generator.py    # AI-powered tax rule generation
└── profiles/
    ├── __init__.py             # ALL_PROFILES registry
    ├── india.py                # NSE/BSE profile
    ├── united_states.py        # NYSE/NASDAQ profile
    ├── united_kingdom.py       # LSE profile
    ├── australia.py            # ASX profile
    ├── canada.py               # TSX profile
    ├── germany.py              # XETRA profile
    ├── japan.py                # JPX profile
    └── singapore.py            # SGX profile
```

## Configuration

Market selection is persisted to `config/market.yaml`:

```yaml
country: US
country_name: United States
currency: USD
timezone: America/New_York
primary_exchange: NYSE
benchmark_index: S&P 500
benchmark_symbol: ^GSPC
selected_at: '2025-05-06T10:30:00+00:00'
```

The trading engine reads this at startup via `Config.market` (backward compatible — defaults to India if no market.yaml exists).

## Volatility Guard

The RMS volatility guard now uses the market-specific benchmark:

- **India**: Monitors Nifty 50 via `nifty:current_price` Redis key
- **US**: Monitors S&P 500 via `sp500:current_price` Redis key
- **UK**: Monitors FTSE 100 via `ftse100:current_price` Redis key
- etc.

The ingestion layer must publish benchmark prices to the correct Redis key based on the active market's `benchmark_redis_key` setting.

## Adding a New Country

1. Create `src/markets/profiles/new_country.py` with a `MarketProfile`
2. Add it to `src/markets/profiles/__init__.py`
3. Implement a broker adapter in `src/ingestion/` (implements `BrokerInterface`)
4. Add news sources for sentiment analysis
5. Test with paper trading

## Limitations

- Tax calculations are **estimates only** — not suitable for official filing
- AI-generated tax profiles require user verification
- Broker adapters must be implemented per-broker (the interface is standardized)
- Holiday calendars are not yet implemented (planned for Phase 2)
- Multi-currency portfolio tracking is not yet supported (planned for Phase 2)
