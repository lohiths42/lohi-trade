# Lohi-TRADE Backend Gateway

FastAPI service that bridges the React frontend with the existing LOHI-TRADE backend (Redis Streams + SQLite).

## Architecture

```
React Frontend ──HTTP/WS──▶ FastAPI Gateway ──▶ Redis Streams + SQLite
     (3000)                    (8000)              (existing backend)
```

The gateway is read-only against the existing infrastructure — it queries SQLite, consumes Redis Streams, and publishes user commands back to `stream:commands`.

## Setup

### Prerequisites

- Python 3.11+
- Redis 7.0+ running on localhost:6379
- Existing LOHI-TRADE backend with populated SQLite DB and Redis Streams

### Install & Run

```bash
cd ..
pip install lohi-trade
cd backend-gateway
cp .env.example .env    # Edit as needed
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_HOST` | `localhost` | Redis server hostname |
| `REDIS_PORT` | `6379` | Redis server port |
| `REDIS_DB` | `0` | Redis database index |
| `DB_PATH` | `../data/lohi_trade.db` | Path to SQLite database |
| `CONFIG_PATH` | `../config/settings.yaml` | Path to trading config YAML |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowed origins |
| `SECRET_KEY` | `change-me-in-production` | Secret key for signing |

## API Reference

### Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Redis + SQLite connectivity check |

### Positions

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/positions` | List open positions |
| POST | `/api/positions/{id}/close` | Close a position (publishes to stream:commands) |

### Orders

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/orders` | List orders (supports status/symbol filters) |
| POST | `/api/orders/{id}/cancel` | Cancel a pending order |

### Trades

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/trades` | Trade history |

### Signals

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/signals` | Recent trading signals |

### Bias & News

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/bias` | Current bias for all tickers |
| GET | `/api/bias/{ticker}` | Bias for a specific ticker |
| GET | `/api/news` | Recent news articles with sentiment |

### Analytics

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/analytics/equity-curve` | Equity curve data points |
| GET | `/api/analytics/daily-pnl` | Daily P&L breakdown |
| GET | `/api/analytics/strategy-performance` | Per-strategy metrics |

### Configuration

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/config` | Current trading configuration |
| PUT | `/api/config` | Update trading configuration |

### Kill Switch

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/kill-switch` | Kill switch status |
| POST | `/api/kill-switch/toggle` | Toggle kill switch on/off |

### Logs

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/logs` | System audit logs (supports level/component filters) |

## WebSocket Events

The gateway runs a Socket.IO server. The frontend connects to the same host/port.

| Event | Direction | Payload | Source |
|-------|-----------|---------|--------|
| `price_tick` | Server → Client | `{symbol, ltp, volume, timestamp}` | `stream:ticks:*` |
| `position_update` | Server → Client | `{id, symbol, side, qty, cmp, pnl}` | Computed from ticks |
| `order_update` | Server → Client | `{orderId, status, filledQty}` | Redis stream / DB poll |
| `signal_generated` | Server → Client | `{symbol, strategy, side, price}` | `stream:signals` |
| `bias_update` | Server → Client | `{ticker, bias, score, confidence}` | `stream:bias:*` |
| `kill_switch_toggle` | Server → Client | `{active: boolean}` | Redis key change |

The frontend also emits commands via Socket.IO: `close_position`, `cancel_order`, `toggle_kill_switch`.

## Docker

### Standalone

```bash
docker build -t lohi-trade-gateway .
docker run -p 8000:8000 --env-file .env lohi-trade-gateway
```

### With Docker Compose (from project root)

```bash
docker-compose up -d
```

This starts both Redis and the gateway. The gateway waits for Redis to be healthy before starting.

```yaml
# Relevant docker-compose services:
# - redis:   port 6379, persistent storage
# - gateway: port 8000, mounts data/ and config/ volumes
```

## Project Structure

```
backend-gateway/
├── app/
│   ├── main.py              # FastAPI app + Socket.IO mount
│   ├── config.py            # Environment-based configuration
│   ├── websocket.py         # Socket.IO event handlers
│   ├── models/              # Pydantic response models
│   │   ├── analytics.py
│   │   ├── bias.py
│   │   ├── logs.py
│   │   ├── orders.py
│   │   ├── positions.py
│   │   └── trades.py
│   ├── routers/             # REST API routers
│   │   ├── analytics.py
│   │   ├── bias.py
│   │   ├── config.py
│   │   ├── health.py
│   │   ├── kill_switch.py
│   │   ├── logs.py
│   │   ├── orders.py
│   │   ├── positions.py
│   │   ├── signals.py
│   │   └── trades.py
│   └── services/
│       ├── analytics_service.py  # Equity curve, P&L computation
│       ├── db_service.py         # SQLite query layer
│       └── redis_consumer.py     # Redis Stream → Socket.IO bridge
├── .env.example
├── Dockerfile
└── requirements.txt
```
