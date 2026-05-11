# LOHI-TRADE Project Structure

## Directory Layout

```
LOHI-TRADE/
├── .kiro/                          # Kiro IDE specifications
│   └── specs/
│       └── lohi-trade/
│           ├── requirements.md     # System requirements
│           ├── design.md          # Architecture and design
│           └── tasks.md           # Implementation tasks
│
├── src/                           # Source code
│   ├── __init__.py
│   ├── ingestion/                # Data ingestion layer
│   │   └── __init__.py
│   ├── soldier/                  # Technical analysis engine
│   │   └── __init__.py
│   ├── commander/                # AI/NLP sentiment engine
│   │   └── __init__.py
│   ├── execution/                # Order execution and risk management
│   │   └── __init__.py
│   ├── state/                    # State management (Redis, databases)
│   │   └── __init__.py
│   ├── ui/                       # User interfaces
│   │   └── __init__.py
│   └── utils/                    # Utilities and helpers
│       └── __init__.py
│
├── tests/                         # Test suite
│   └── __init__.py
│
├── data/                          # Data storage (gitignored)
│   ├── backups/                  # Database backups
│   ├── logs/                     # Application logs
│   └── models/                   # ML models (FinBERT ONNX)
│
├── config/                        # Configuration files
│   └── settings.yaml.template    # Configuration template
│
├── scripts/                       # Utility scripts
│   ├── startup.py                # System startup script
│   └── shutdown.py               # System shutdown script
│
├── notebooks/                     # Jupyter notebooks for analysis
│
├── pyproject.toml                # Project configuration and dependencies
├── docker-compose.yml            # Redis container configuration
├── .gitignore                    # Git ignore rules
├── .env.template                 # Environment variables template
├── README.md                     # Project documentation
└── PROJECT_STRUCTURE.md          # This file
```

## Module Responsibilities

### src/ingestion/
- WebSocket client for broker APIs (Shoonya, Angel One)
- RSS feed poller for financial news
- NSE announcements fetcher
- Tick data publishing to Event Bus

### src/soldier/
- Candle builder (tick aggregation)
- Indicator engine (RSI, MACD, Bollinger Bands, etc.)
- Strategy engine (Mean Reversion, Trend Following, ORB)
- Signal generation

### src/commander/
- Entity resolver (spaCy NER)
- Sentiment analyzer (FinBERT)
- Bias calculator with time decay
- News deduplication

### src/execution/
- Risk Management System (9 pre-order checks)
- Position sizer (ATR-based)
- Order Management System
- Kill switch mechanism
- Stop-loss and target management

### src/state/
- Redis client wrapper
- Event Bus abstraction (Redis Streams)
- SQLite database manager
- DuckDB historical data manager

### src/ui/
- Streamlit dashboard
- Telegram bot
- Notification system

### src/utils/
- Configuration loader
- Structured logging
- Helper functions
- Constants and enums

## Data Flow

1. **Ingestion** → Event Bus (Redis Streams)
2. **Event Bus** → The Soldier (technical analysis)
3. **Event Bus** → The Commander (sentiment analysis)
4. **Signals + Bias** → Risk Management System
5. **Validated Orders** → Order Management System
6. **Executions** → State Layer (SQLite/DuckDB)
7. **State** → User Interfaces (Dashboard, Telegram)

## Configuration Files

- `.env`: Environment variables (credentials, secrets)
- `config/settings.yaml`: System configuration (capital, risk limits, strategies)
- `docker-compose.yml`: Redis container configuration
- `pyproject.toml`: Python project metadata and dependencies

## Data Files (gitignored)

- `data/*.db`: SQLite databases
- `data/*.duckdb`: DuckDB historical data
- `data/backups/*.db`: Database backups
- `data/logs/*.log`: Application logs
- `data/models/*.onnx`: ML models
- `nifty50_tokens.json`: Instrument master
- `ticker_map.json`: Company name to ticker mapping

## Next Steps

1. Implement core configuration management (Task 2)
2. Set up Redis and Event Bus infrastructure (Task 3)
3. Implement database layer (Task 4)
4. Implement structured logging (Task 5)

Refer to `.kiro/specs/lohi-trade/tasks.md` for the complete implementation plan.
