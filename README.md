# LOHI-TRADE

**AI-Powered Algorithmic Trading Platform for Indian Equity Markets (NSE/BSE)**

> **Open Source & Free** - MIT License. No paid APIs required. No commercial restrictions.

LOHI-TRADE is a full-stack algorithmic trading platform that combines real-time technical analysis with FinBERT-based news sentiment to trade Indian equities. It ships as a multi-process Python trading engine, a FastAPI backend gateway, a React web dashboard, and Docker-managed infrastructure — all wired together through Redis Streams and a shared PostgreSQL state layer.

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Architecture](#architecture)
3. [Prerequisites](#prerequisites)
4. [Quick Start](#quick-start)
5. [Manual Setup](#manual-setup)
6. [Configuration Reference](#configuration-reference)
7. [External Services](#external-services)
8. [Development Workflow](#development-workflow)
9. [Testing](#testing)
10. [Deployment](#deployment)
11. [Troubleshooting](#troubleshooting)
12. [Contributing](#contributing)
13. [License](#license)

---

## Project Overview

### What It Does

LOHI-TRADE ingests live market data and financial news, derives trading signals from two independent analysis engines, filters them through a comprehensive risk management system, and executes orders — either on real broker accounts or in a paper-trading simulator.

### Key Capabilities

- **Dual-Engine Signal Generation** — "The Soldier" (fast-path technical analysis on 1m/5m/15m candles) and "The Commander" (slow-path NLP sentiment via FinBERT) converge at the order gate for high-confidence signals.
- **AI Research Dashboard** — Retrieval-grounded equity research briefs with inline citations, powered by NVIDIA NIM or local Ollama models.
- **9-Check Risk Management System** — Kill switch, position limits, volatility guards, bias alignment, and more.
- **Multi-Broker Support** — Shoonya (Finvasia), Angel One, Zerodha Kite, Groww, and Nubra.io behind a unified `BrokerInterface`.
- **Paper Trading** — Simulated fills with configurable latency and slippage for risk-free validation.
- **Real-Time Dashboard** — React + Socket.IO web app with live P&L, positions, orders, analytics, and a trading chatbot.
- **Telegram Notifications** — Trade alerts, P&L updates, and kill switch commands via Telegram bot.
- **One-Command Setup** — `pip install lohi-trade && lohi setup` bootstraps the stack and opens a browser-based configuration wizard.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CLIENTS                                         │
│   Browser (React)    │    Telegram Bot    │    Mobile Apps (iOS/Android)      │
└──────────┬───────────┴─────────┬──────────┴──────────┬──────────────────────┘
           │ HTTP/WS :3000       │                     │ HTTP/WS
           ▼                     ▼                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    BACKEND GATEWAY (FastAPI, port 8000)                      │
│                                                                             │
│  JWT Auth · RBAC · Rate Limiting · Input Sanitization · Socket.IO           │
│  Routers: auth · orders · positions · trades · signals · bias · analytics   │
│           screener · watchlist · chatbot · market_data · setup · health      │
│                                                                             │
│  Services: setup_service · credential_store · service_registry              │
│            connection_tester · auth · screener · chatbot · live_data         │
└──────┬──────────────────────────────────┬───────────────────────────────────┘
       │                                  │
       ▼                                  ▼
┌──────────────────┐            ┌──────────────────────────────────────────────┐
│  INFRASTRUCTURE  │            │           TRADING ENGINE (src/)               │
│                  │            │                                               │
│  PostgreSQL :5432│◄──────────►│  Ingestion ──► The Soldier (TA signals)       │
│  Redis      :6379│◄──────────►│              ──► The Commander (NLP bias)     │
│                  │            │              ──► RMS (9 checks) ──► OMS       │
└──────────────────┘            │              ──► Position Manager             │
                                │                                               │
                                │  Research Dashboard (AI briefs + citations)    │
                                └──────────────────────────────────────────────┘
                                               │
                                               ▼
                                ┌──────────────────────────────────────────────┐
                                │          EXTERNAL SERVICES                    │
                                │                                               │
                                │  NVIDIA NIM / Ollama ─── AI Inference         │
                                │  Nubra.io ────────────── Live Market Data     │
                                │  Shoonya / Angel One ─── Order Execution      │
                                │  Telegram ────────────── Notifications        │
                                └──────────────────────────────────────────────┘
```

### Data Flow Summary

1. **Market data** flows in from broker WebSockets via the ingestion layer
2. **The Soldier** builds candles, computes indicators, generates technical signals
3. **The Commander** polls financial news, runs FinBERT sentiment, computes directional bias
4. **RMS** gates signals — only allows trades where technical signal and sentiment bias align
5. **OMS** executes orders on the configured broker (or paper-trading simulator)
6. **Redis Streams** connect all components with at-least-once delivery
7. **Backend Gateway** bridges Redis events to the web dashboard via Socket.IO

---

## Prerequisites

| Dependency | Minimum Version | Purpose |
|------------|----------------|---------|
| **Python** | 3.11+ | Backend gateway and trading engine |
| **Node.js** | 18.0+ | Frontend build and dev server |
| **Docker** | 20.10+ | Container runtime for PostgreSQL and Redis |
| **npm** | 9.0+ | Frontend package management |
| **Git** | 2.0+ | Source control |
| **ta-lib** | 0.4.0+ | Technical analysis C headers |

### OS-Specific Setup Commands

**macOS:**
```bash
brew install python@3.11 node@18 git curl lsof ta-lib
brew install --cask docker
```

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv nodejs npm git curl lsof
# ta-lib requires building from source on Ubuntu:
wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz
tar -xzf ta-lib-0.4.0-src.tar.gz && cd ta-lib/
./configure --prefix=/usr && make && sudo make install
```

### Optional

| Dependency | Purpose |
|------------|---------|
| **Ollama** | Local AI inference (alternative to NVIDIA NIM cloud) |

---

## Quick Start

The fastest way to get LOHI-TRADE running:

```bash
# 1. Clone the repository
git clone https://github.com/AdhirU/Lohi-Trade-OpenSource.git
cd Lohi-Trade-OpenSource

# 2. Check Prerequisites (Optional but recommended)
./scripts/check_prereqs.sh

# 3. Install LOHI-TRADE
pip install ".[all]"

# 4. Run the setup command
# If you don't want to use Docker, use: lohi setup --skip-docker
lohi setup

# 5. Configure external services in the browser wizard
#    (opens automatically at http://localhost:3000/setup/integrations)

# 6. Start trading!
```

### 🧠 NVIDIA NIM Integration (Optional)
LOHI-TRADE supports **NVIDIA NIM** for high-performance AI inference and research generation without running heavy local models.
To enable it:
1. Obtain an API key from [build.nvidia.com](https://build.nvidia.com/).
2. Set it in your `.env` or `.env.research` file:
   ```env
   NIM_API_KEY=nvapi-your-key-here
   NIM_MODEL=meta/llama3.1-8b-instruct
   ```
If provided, LOHI-TRADE will use NVIDIA NIM instead of falling back to Ollama.

The `lohi setup` command handles the runtime bootstrap:
- Checks system dependencies and reports any missing ones with install commands
- Uses the packaged Python dependencies from `pip install lohi-trade`
- Installs frontend dependencies via `npm ci`
- Starts Docker infrastructure (PostgreSQL + Redis)
- Waits for healthy containers
- Launches the backend gateway (port 8000) and frontend dev server (port 3000)
- Opens your browser to the Setup Wizard

### Optional Python Features

LOHI-TRADE ships with only **core dependencies** installed. Optional features can be added:

```bash
# Machine Learning features (sentiment analysis, market prediction)
pip install lohi-trade[ml]

# Backtesting and optimization
pip install lohi-trade[backtesting]

# Streamlit dashboard (alternative to React)
pip install lohi-trade[dashboard]

# Nubra.io real-time ticker support
pip install lohi-trade[nubra]

# All features
pip install lohi-trade[all]

# Development (testing, linting)
pip install lohi-trade[all,dev]
```

**Note**: These features are **completely optional**. Paper trading works without any of them.

---

## Free vs Optional Services

| Feature | Default | Free Option | Paid Option |
|---------|---------|-------------|-------------|
| **Paper Trading** | ✅ Included | Built-in | N/A |
| **Technical Analysis** | ✅ Included | ta-lib | N/A |
| **Market Data** | ✅ Included | yfinance | Nubra.io |
| **News Sentiment** | ⚠️ Optional | Ollama (local) | NVIDIA NIM, OpenAI |
| **Research Dashboard** | ⚠️ Optional | Ollama (local) | NVIDIA NIM |
| **Broker APIs** | ✅ Multiple | Zerodha, Groww | Angel One, Shoonya |

**TL;DR**: You can run LOHI-TRADE completely free without entering any API keys. Paid services are only needed if you want cloud AI features or specific brokers.

---

## Manual Setup

If you prefer step-by-step control over the bootstrap process:

### 1. Install System Dependencies

**macOS (Homebrew):**
```bash
brew install docker docker-compose node python@3.11
```

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install docker.io docker-compose-plugin nodejs npm python3.11 python3.11-venv
```

**Fedora/RHEL:**
```bash
sudo dnf install docker docker-compose nodejs npm python3.11
```

**Arch Linux:**
```bash
sudo pacman -S docker docker-compose nodejs npm python
```

### 2. Start Docker Infrastructure

```bash
docker compose up -d redis postgres
```

Wait for containers to be healthy:
```bash
docker compose ps  # Both should show "healthy"
```

### 3. Set Up Python Environment

```bash
pip install lohi-trade
lohi setup
```

### 4. Set Up Frontend

```bash
cd "Lohi-TRADE Web App Design"
npm ci
cd ..
```

### 5. Run Database Migrations

```bash
cd backend-gateway
alembic upgrade head
cd ..
```

### 6. Configure Environment

```bash
cp .env.template .env
cp .env.research.template .env.research
# Edit .env and .env.research with your credentials
```

### 7. Start the Application

```bash
# Terminal 1: Backend gateway
cd backend-gateway
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2: Frontend dev server
cd "Lohi-TRADE Web App Design"
npm run dev

# Terminal 3 (optional): Trading engine
python scripts/startup.py
```

### 8. Access the Application

- **Web Dashboard:** http://localhost:3000
- **Setup Wizard:** http://localhost:3000/setup/integrations
- **API Docs:** http://localhost:8000/docs
- **Default credentials:** `admin` / `admin123`

---

## Configuration Reference

### Environment Variables (`.env`)

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `SHOONYA_API_KEY` | Shoonya broker API key | — | For live trading |
| `SHOONYA_CLIENT_ID` | Shoonya trading account client ID | — | For live trading |
| `SHOONYA_PASSWORD` | Shoonya account password | — | For live trading |
| `ANGELONE_API_KEY` | Angel One broker API key | — | Optional |
| `ANGELONE_CLIENT_ID` | Angel One client ID | — | Optional |
| `ANGELONE_PASSWORD` | Angel One password | — | Optional |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token from @BotFather | — | Optional |
| `TELEGRAM_CHAT_ID` | Telegram chat/group ID for notifications | — | Optional |
| `NUBRA_PHONE_NO` | Registered phone number on Nubra.io | — | For live data |
| `NUBRA_MPIN` | 4-6 digit MPIN for Nubra.io | — | For live data |
| `NUBRA_TOTP_SECRET` | Base32 TOTP secret from Nubra.io 2FA | — | For live data |
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://lohi:lohi@localhost:5432/lohitrade` | Yes |
| `REDIS_HOST` | Redis server hostname | `localhost` | Yes |
| `REDIS_PORT` | Redis server port | `6379` | Yes |
| `JWT_SECRET` | Secret for JWT token signing (32+ chars) | `change-me-in-production` | Yes |
| `ADMIN_USERNAME` | Default admin username | `admin` | Yes |
| `ADMIN_PASSWORD` | Default admin password | `admin123` | Yes |
| `ENVIRONMENT` | Runtime mode | `development` | Yes |

### Research Environment Variables (`.env.research`)

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `NVIDIA_NIM_API_KEY` | NVIDIA NIM API key for cloud AI inference | — | For cloud AI |
| `OPENAI_API_KEY` | OpenAI API key (alternate provider) | — | Optional |
| `ANTHROPIC_API_KEY` | Anthropic Claude API key | — | Optional |
| `GOOGLE_API_KEY` | Google Gemini API key | — | Optional |
| `GROQ_API_KEY` | Groq API key | — | Optional |
| `TOGETHER_API_KEY` | Together AI API key | — | Optional |
| `OPENROUTER_API_KEY` | OpenRouter API key | — | Optional |
| `LOHI_RESEARCH_OFFLINE` | Enable fully-offline mode (Ollama) | `false` | Optional |
| `QDRANT_URL` | Qdrant vector store URL | — | Optional |

### Application Config (`config/settings.yaml`)

Non-secret configuration lives in `config/settings.yaml`. Key sections:

| Section | Purpose |
|---------|---------|
| `capital` | Total capital, risk per trade, max position size, max daily loss |
| `risk_limits` | Max open positions, max orders/day, cooldown, volatility guard |
| `trading_hours` | Market open/close times, pre-market window |
| `broker` | Primary/backup broker selection |
| `strategies` | Enable/disable and tune Mean Reversion, Trend Following, ORB |
| `sentiment` | FinBERT thresholds, bias decay half-life |
| `paper_trading` | Enable/disable, simulated delay and slippage |
| `ml_strategy` | ML overlay confidence threshold |
| `symbols` | Watchlist of NSE symbols to trade |

See [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) for the full reference.

---

## External Services

| Service | Purpose | Required? | Signup URL |
|---------|---------|-----------|------------|
| **NVIDIA NIM** | Cloud AI inference for Research Dashboard LLM capabilities | Optional (Ollama is alternative) | https://build.nvidia.com |
| **Nubra.io** | Exchange-sourced NSE/BSE live market data feed | Required for live data | https://nubra.io |
| **Shoonya (Finvasia)** | Primary broker for live order execution | Optional (paper trading works without) | https://shoonya.finvasia.com |
| **Angel One** | Backup broker for order execution | Optional | https://www.angelone.in |
| **Telegram** | Trade notifications and bot commands | Optional (alerts also in web UI) | https://core.telegram.org/bots |
| **Ollama** | Local AI inference (no cloud dependency) | Optional (alternative to NVIDIA NIM) | https://ollama.ai |

### Service Details

**NVIDIA NIM** — Powers the Research Dashboard's AI analysis. Provides cloud-hosted LLM inference using models like Llama 3.1. Free tier available. Set `NVIDIA_NIM_API_KEY` in `.env.research`.

**Nubra.io** — Provides exchange-sourced real-time market data for NSE/BSE. Required for live quotes and market data feeds. Requires phone number, MPIN, and TOTP secret.

**Shoonya (Finvasia)** — Primary broker integration for live order execution. Without it, the platform operates in paper-trading mode only. Requires API key, client ID, and password.

**Telegram** — Sends trade notifications, P&L alerts, and supports commands (`/status`, `/pnl`, `/killswitch`). Create a bot via @BotFather and get your chat ID.

**Ollama** — Run AI models locally without any cloud API keys. Install Ollama, pull a model (`ollama pull llama3.1:8b`), and set `LOHI_RESEARCH_OFFLINE=true` in `.env.research`.

---

## Development Workflow

### Project Structure

```
Lohi-Trade-OpenSource/
├── src/                          # Python trading engine
├── backend-gateway/              # FastAPI REST + Socket.IO gateway
├── Lohi-TRADE Web App Design/    # React + Vite + TypeScript dashboard
├── mobile/                       # iOS (SwiftUI) + Android (Compose) apps
├── infra/                        # AWS CDK infrastructure
├── scripts/                      # Startup, shutdown, data scripts
├── tests/                        # Engine unit + property-based tests
├── config/                       # settings.yaml + keywords.json
├── docs/                         # Architecture and reference docs
├── docker-compose.yml            # Infrastructure services
├── setup.sh                      # One-command bootstrap
└── pyproject.toml                # Python project metadata
```

### Running the Backend

```bash
source lohi_trade_venv/bin/activate
cd backend-gateway
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Running the Frontend

```bash
cd "Lohi-TRADE Web App Design"
npm run dev
```

### Linting and Formatting

**Python (backend + engine):**
```bash
# Lint
ruff check .

# Format
ruff format .

# Type checking
mypy backend-gateway/app/
```

**TypeScript (frontend):**
```bash
cd "Lohi-TRADE Web App Design"

# Lint
npm run lint

# Format
npx prettier --write src/
```

**Shell scripts:**
```bash
shellcheck setup.sh
```

### Code Style

- Python: follows `ruff` defaults (PEP 8 + modern conventions)
- TypeScript: ESLint + Prettier with project config
- Shell: POSIX-compatible bash (3.2+), validated with `shellcheck`

---

## Testing

### Backend Tests (pytest + Hypothesis)

```bash
# Run all backend tests
cd backend-gateway
pytest

# Run with verbose output
pytest -v

# Run a specific test file
pytest tests/test_setup_router.py

# Run property-based tests only
pytest -m "hypothesis"

# Run with coverage
pytest --cov=app --cov-report=term-missing
```

### Engine Tests (pytest + Hypothesis)

```bash
# Run trading engine tests
pytest tests/

# Run property-based tests
pytest tests/ -m "hypothesis"
```

### Frontend Tests (Vitest + fast-check)

```bash
cd "Lohi-TRADE Web App Design"

# Run all tests
npm test

# Run tests in watch mode
npm run test:watch

# Run with coverage
npm run test:coverage

# Run a specific test file
npx vitest run src/components/setup/__tests__/SetupSummary.test.tsx
```

### Property-Based Tests

LOHI-TRADE uses property-based testing extensively:

- **Backend (Hypothesis):** Tests credential validation, service registry round-trips, feature availability logic, credential persistence, and port conflict detection.
- **Frontend (fast-check):** Tests service status rendering completeness, feature availability correctness, CSV export, and store behavior.

Property tests generate hundreds of random inputs to verify that invariants hold across the entire input space, catching edge cases that example-based tests miss.

### Integration Tests

```bash
# Full Docker stack test
docker compose up --build
# Then run integration test suite against running services
pytest tests/integration/ -v
```

---

## Deployment

### Production Considerations

1. **Change default credentials** — Update `JWT_SECRET`, `ADMIN_USERNAME`, and `ADMIN_PASSWORD` in `.env`
2. **Use strong JWT secret** — At least 32 characters, randomly generated
3. **Secure .env files** — Ensure `chmod 600` on all `.env` files
4. **Enable HTTPS** — Put a reverse proxy (nginx/Caddy) in front of the gateway
5. **Database backups** — Configure automated PostgreSQL backups
6. **Monitoring** — Set up health check monitoring on `/api/health`
7. **Rate limiting** — Review and adjust rate limits for production traffic
8. **Kill switch** — Test the kill switch mechanism before going live

### Docker Production Build

```bash
docker compose -f docker-compose.yml up --build -d
```

### AWS Deployment

The `infra/` directory contains AWS CDK stacks for production deployment:

```bash
cd infra
pip install -r requirements.txt
cdk deploy --all
```

This provisions:
- VPC with public/private/isolated subnets
- RDS PostgreSQL + ElastiCache Redis
- ECS Fargate cluster running gateway + engine
- CloudFront CDN for the frontend
- CloudWatch monitoring and alarms

### Environment Modes

| Mode | `ENVIRONMENT` value | Behavior |
|------|-------------------|----------|
| Development | `development` | Hot reload, verbose logging, relaxed CORS |
| Paper Trading | `paper_trading` | Simulated fills, no real orders |
| Production | `production` | Real broker orders, strict security, minimal logging |

---

## Troubleshooting

### Docker Issues

**Docker daemon not running:**
```bash
# macOS
open -a Docker

# Linux
sudo systemctl start docker
```

**Containers won't start:**
```bash
# Check container logs
docker compose logs redis
docker compose logs postgres

# Reset volumes (WARNING: deletes data)
docker compose down -v
docker compose up -d
```

**Permission denied on Docker socket (Linux):**
```bash
sudo usermod -aG docker $USER
# Log out and back in for group change to take effect
```

### Port Conflicts

**Port already in use:**
```bash
# Find what's using a port
lsof -i :5432   # PostgreSQL
lsof -i :6379   # Redis
lsof -i :8000   # Backend
lsof -i :3000   # Frontend

# Kill the conflicting process
kill -9 <PID>
```

**Common conflicts:**
- Port 5432: Another PostgreSQL instance or pgAdmin
- Port 6379: Another Redis instance
- Port 8000: Other Python web servers
- Port 3000: Other Node.js dev servers (Create React App, etc.)

### Database Issues

**Connection refused:**
```bash
# Verify PostgreSQL is running
docker compose ps postgres

# Check if the database exists
docker compose exec postgres psql -U lohi -d lohitrade -c "SELECT 1;"

# Re-run migrations
cd backend-gateway && alembic upgrade head
```

**Migration errors:**
```bash
# Reset migrations (WARNING: drops all tables)
cd backend-gateway
alembic downgrade base
alembic upgrade head
```

### API Key Errors

**NVIDIA NIM "Unauthorized":**
- Verify your key starts with `nvapi-`
- Check the key hasn't expired at https://build.nvidia.com
- Ensure the key is in `.env.research`, not `.env`

**Nubra.io login failure:**
- Verify phone number is exactly 10 digits
- Check MPIN is 4-6 digits
- Ensure TOTP secret is the Base32 string (uppercase letters + digits 2-7)

**Shoonya authentication error:**
- Verify client ID is uppercase alphanumeric
- Check API key is active in the Shoonya developer portal
- Ensure password hasn't been changed since configuration

**Telegram bot not responding:**
- Verify token format: `<numbers>:<alphanumeric string>`
- Test with: `curl https://api.telegram.org/bot<TOKEN>/getMe`
- Ensure the bot has been started (send `/start` to it)

### macOS vs Linux Differences

| Issue | macOS | Linux |
|-------|-------|-------|
| Docker | Docker Desktop required | Native Docker Engine |
| File permissions | `chmod` works but less strict | `chmod 600` enforced |
| Port binding | May need `127.0.0.1:` prefix | Binds to `0.0.0.0` by default |
| Python | `python3.11` via Homebrew | System package or pyenv |
| Bash version | 3.2 (default), 5.x via brew | 5.x (default) |
| `open` command | Opens browser | Use `xdg-open` instead |

### Common Fixes

**"Module not found" errors:**
```bash
# Ensure virtual environment is activated
source lohi_trade_venv/bin/activate

# Reinstall dependencies
pip install lohi-trade --upgrade
```

**Frontend build errors:**
```bash
cd "Lohi-TRADE Web App Design"
rm -rf node_modules
npm ci
```

**Redis connection refused:**
```bash
# Check Redis is healthy
docker compose exec redis redis-cli ping
# Should return: PONG
```

---

## Contributing

### Getting Started

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Make your changes
4. Run tests: `pytest` (backend) and `npm test` (frontend)
5. Lint your code: `ruff check .` and `npm run lint`
6. Commit with a descriptive message
7. Push and open a Pull Request

### Guidelines

- **Tests required** — All new features must include unit tests. Property-based tests are encouraged for pure logic.
- **Type safety** — Use type hints in Python and TypeScript strict mode.
- **Documentation** — Update relevant docs when changing behavior.
- **Commit messages** — Use conventional commits: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`.
- **Branch naming** — `feature/`, `fix/`, `docs/`, `refactor/` prefixes.
- **Code review** — All PRs require at least one approval.

### Architecture Decisions

Major architectural changes should be discussed in an issue first. The project uses:
- Event-driven architecture via Redis Streams
- Separation of concerns: trading engine, gateway, and frontend are independent
- Property-based testing for correctness guarantees
- Graceful degradation when optional services are unconfigured

---

## License

This project is licensed under the terms specified in the [LICENSE](LICENSE) file.

---

<p align="center">
  <strong>LOHI-TRADE</strong> — AI-powered algorithmic trading for Indian markets
</p>
