#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Lohi-TRADE — One-Click Launcher
# Starts the backend gateway (FastAPI) and frontend (Vite) in one go.
# Usage:  ./start.sh          (start everything)
#         ./start.sh stop     (kill everything)
# ─────────────────────────────────────────────────────────────────────────────

set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend-gateway"
FRONTEND_DIR="$ROOT_DIR/Lohi-TRADE Web App Design"
LOG_DIR="$ROOT_DIR/logs"
BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"
PID_FILE="$LOG_DIR/.lohi-pids"

BACKEND_PORT=8000
FRONTEND_PORT=3000

# ─── Virtual Environment ────────────────────────────────────────────────────
# Activate the project venv so uvicorn/fastapi are available.
# The venv is kept OUTSIDE this folder (one level up), alongside
# Lohi-Trade-OpenSource/.  We also fall back to an in-repo .venv for flexibility.
PARENT_DIR="$(cd "$ROOT_DIR/.." && pwd)"
if [ -f "$PARENT_DIR/lohi_trade_venv/bin/activate" ]; then
  source "$PARENT_DIR/lohi_trade_venv/bin/activate"
elif [ -f "$ROOT_DIR/lohi_trade_venv/bin/activate" ]; then
  source "$ROOT_DIR/lohi_trade_venv/bin/activate"
elif [ -f "$ROOT_DIR/.venv/bin/activate" ]; then
  source "$ROOT_DIR/.venv/bin/activate"
fi

# Load nvm in non-interactive shells so `npx` is available when Node was
# installed via nvm instead of a system package manager.
if ! command -v npx >/dev/null 2>&1; then
  export NVM_DIR="$HOME/.nvm"
  if [ -s "$NVM_DIR/nvm.sh" ]; then
    # shellcheck disable=SC1090
    . "$NVM_DIR/nvm.sh"
  fi
fi

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# ─── Helpers ─────────────────────────────────────────────────────────────────

banner() {
  echo ""
  echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════╗${NC}"
  echo -e "${CYAN}${BOLD}║          🚀  Lohi-TRADE Launcher         ║${NC}"
  echo -e "${CYAN}${BOLD}╚══════════════════════════════════════════╝${NC}"
  echo ""
}

log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; }

kill_port() {
  local port=$1
  local pids
  pids=$(lsof -ti :"$port" 2>/dev/null || true)
  if [ -n "$pids" ]; then
    echo "$pids" | xargs kill -9 2>/dev/null || true
    warn "Killed existing process on port $port"
  fi
}

wait_for_port() {
  local port=$1
  local name=$2
  local max_wait=30
  local waited=0
  while ! lsof -ti :"$port" >/dev/null 2>&1; do
    sleep 1
    waited=$((waited + 1))
    if [ $waited -ge $max_wait ]; then
      err "$name failed to start within ${max_wait}s"
      err "Check logs: $3"
      exit 1
    fi
  done
  log "$name is up on port $port (${waited}s)"
}

# ─── Stop Mode ───────────────────────────────────────────────────────────────

stop_all() {
  banner
  echo -e "${YELLOW}${BOLD}Stopping Lohi-TRADE...${NC}"
  echo ""

  if [ -f "$PID_FILE" ]; then
    while read -r pid; do
      if kill -0 "$pid" 2>/dev/null; then
        kill -9 "$pid" 2>/dev/null || true
        log "Killed PID $pid"
      fi
    done < "$PID_FILE"
    rm -f "$PID_FILE"
  fi

  # Also clean up by port in case PIDs are stale
  kill_port $BACKEND_PORT
  kill_port $FRONTEND_PORT

  log "All services stopped"
  exit 0
}

if [ "${1:-}" = "stop" ]; then
  stop_all
fi

# ─── Start Mode ──────────────────────────────────────────────────────────────

banner

# Create log directory
mkdir -p "$LOG_DIR"

# Clean up any existing processes on our ports
echo -e "${BOLD}Cleaning up...${NC}"
kill_port $BACKEND_PORT
kill_port $FRONTEND_PORT
sleep 1

# ── 1. Start Backend Gateway ────────────────────────────────────────────────

echo ""
echo -e "${BOLD}Starting Backend Gateway...${NC}"

cd "$BACKEND_DIR"
nohup uvicorn app.main:socket_app \
  --host 0.0.0.0 \
  --port $BACKEND_PORT \
  --workers 1 \
  --log-level info \
  > "$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!
cd "$ROOT_DIR"

log "Backend PID: $BACKEND_PID"
wait_for_port $BACKEND_PORT "Backend Gateway" "$BACKEND_LOG"

# ── 2. Start Frontend Dev Server ────────────────────────────────────────────

echo ""
echo -e "${BOLD}Starting Frontend Dev Server...${NC}"

if ! command -v npx >/dev/null 2>&1; then
  err "npx not found. Install Node.js (or nvm) and ensure npx is on PATH."
  exit 1
fi

cd "$FRONTEND_DIR"
nohup npx vite --port $FRONTEND_PORT --host \
  > "$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!
cd "$ROOT_DIR"

log "Frontend PID: $FRONTEND_PID"
wait_for_port $FRONTEND_PORT "Frontend (Vite)" "$FRONTEND_LOG"

# ── 3. Save PIDs ────────────────────────────────────────────────────────────

echo "$BACKEND_PID" > "$PID_FILE"
echo "$FRONTEND_PID" >> "$PID_FILE"

# ── 4. Summary ──────────────────────────────────────────────────────────────

echo ""
echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════╗${NC}"
echo -e "${CYAN}${BOLD}║            All Systems Running            ║${NC}"
echo -e "${CYAN}${BOLD}╠══════════════════════════════════════════╣${NC}"
echo -e "${CYAN}║${NC}  Frontend  →  ${GREEN}http://localhost:${FRONTEND_PORT}${NC}        ${CYAN}║${NC}"
echo -e "${CYAN}║${NC}  Backend   →  ${GREEN}http://localhost:${BACKEND_PORT}${NC}        ${CYAN}║${NC}"
echo -e "${CYAN}║${NC}  API Docs  →  ${GREEN}http://localhost:${BACKEND_PORT}/docs${NC}   ${CYAN}║${NC}"
echo -e "${CYAN}${BOLD}╠══════════════════════════════════════════╣${NC}"
echo -e "${CYAN}║${NC}  Logs: ${YELLOW}logs/backend.log${NC}                  ${CYAN}║${NC}"
echo -e "${CYAN}║${NC}        ${YELLOW}logs/frontend.log${NC}                 ${CYAN}║${NC}"
echo -e "${CYAN}║${NC}  Stop: ${YELLOW}./start.sh stop${NC}                   ${CYAN}║${NC}"
echo -e "${CYAN}${BOLD}╚══════════════════════════════════════════╝${NC}"
echo ""

# ── 5. Open browser ─────────────────────────────────────────────────────────

if command -v open &>/dev/null; then
  sleep 1
  open "http://localhost:$FRONTEND_PORT"
  log "Opened browser"
fi

log "Done. Happy trading! 📈"
