#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Lohi-Research — Plug-and-Play Launcher
# Starts the full Lohi-Research stack alongside the existing LOHI-TRADE
# gateway + frontend:
#   1. Load .env + .env.research
#   2. Pre-flight config check (fail fast with structured error naming
#      the missing key and the file it is expected in — Req 7.6)
#   3. If LOHI_RESEARCH_OFFLINE=true, `ollama pull` the configured model
#   4. mkdir -p data/research/{chroma,uploads,snapshots}
#   5. Delegate to ./start.sh to bring up gateway + frontend
#   6. Start orchestrator.py, indexer.py, snapshotter.py as supervised
#      background processes
# Usage:  ./start-research.sh          (start everything)
#         ./start-research.sh stop     (kill research workers + start.sh stack)
#         ./start-research.sh preflight (run the config check only)
# Satisfies: Req 7.1, Req 7.4, Req 7.6 | Design: §16.1
# ─────────────────────────────────────────────────────────────────────────────

set -u

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$ROOT_DIR/logs"
PID_FILE="$LOG_DIR/.lohi-research-pids"

ORCH_LOG="$LOG_DIR/research-orchestrator.log"
INDEX_LOG="$LOG_DIR/research-indexer.log"
SNAP_LOG="$LOG_DIR/research-snapshotter.log"

DEFAULT_OLLAMA_MODEL="llama3.1:8b"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'
BOLD='\033[1m'

log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1" 1>&2; }

banner() {
  echo ""
  echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════╗${NC}"
  echo -e "${CYAN}${BOLD}║       🔬  Lohi-Research Launcher         ║${NC}"
  echo -e "${CYAN}${BOLD}╚══════════════════════════════════════════╝${NC}"
  echo ""
}

# ─── Virtualenv (matches start.sh) ───────────────────────────────────────────
PARENT_DIR="$(cd "$ROOT_DIR/.." && pwd)"
if [ -f "$PARENT_DIR/lohi_trade_venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "$PARENT_DIR/lohi_trade_venv/bin/activate"
elif [ -f "$ROOT_DIR/lohi_trade_venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "$ROOT_DIR/lohi_trade_venv/bin/activate"
elif [ -f "$ROOT_DIR/.venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.venv/bin/activate"
fi

# Make Python 3 importable as ``python``; prefer the venv.
PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN="python"
fi

# ─── Structured error helper ─────────────────────────────────────────────────
# Emits a JSON-shaped error to stderr matching the gateway's
# ``{"error": {...}}`` envelope so operator tooling can parse it
# (design §5.3, Req 8.8).
structured_error() {
  local code="$1"
  local message="$2"
  local key="${3:-}"
  local file="${4:-}"
  local extras=""
  if [ -n "$key" ]; then extras="${extras},\"config_key\":\"${key}\""; fi
  if [ -n "$file" ]; then extras="${extras},\"expected_in\":\"${file}\""; fi
  err "$message"
  echo "{\"error\":{\"code\":\"${code}\",\"message\":\"${message}\"${extras}}}" 1>&2
}

# ─── Step 1: Load .env + .env.research ───────────────────────────────────────
load_env_files() {
  local envfile
  for envfile in "$ROOT_DIR/.env" "$ROOT_DIR/.env.research"; do
    if [ -f "$envfile" ]; then
      log "Loading ${envfile##$ROOT_DIR/}"
      # Export every KEY=VAL line that isn't a comment or blank. The
      # ``set -a`` / ``set +a`` idiom makes plain ``KEY=VAL`` lines
      # export without eval'ing their contents.
      set -a
      # shellcheck disable=SC1090
      source "$envfile"
      set +a
    else
      warn "${envfile##$ROOT_DIR/} not found (skipping)"
    fi
  done
}

# ─── Step 2: Pre-flight config check ─────────────────────────────────────────
# Fails fast with a structured error naming the missing key and the
# file it is expected in (Req 7.6).
preflight() {
  echo ""
  echo -e "${BOLD}Pre-flight config check...${NC}"

  local settings="$ROOT_DIR/config/settings.yaml"
  if [ ! -f "$settings" ]; then
    structured_error "CONFIG_MISSING" \
      "config/settings.yaml not found" \
      "settings.yaml" \
      "config/settings.yaml"
    return 1
  fi

  # Delegate to a Python helper for the real YAML walk. The helper
  # emits its own structured error; we echo its stderr and exit on
  # non-zero so the caller gets the same ``{"error": {...}}`` envelope.
  #
  # The helper receives the absolute repo root via ``LOHI_ROOT`` so the
  # YAML read is not cwd-dependent — the launcher is expected to work
  # from any directory (Req 7.6 / Req 7.1).
  local preflight_output
  if ! preflight_output="$(LOHI_ROOT="$ROOT_DIR" "$PYTHON_BIN" - <<'PYEOF' 2>&1
"""Pre-flight config walk for start-research.sh.

Exits 0 when every required key is set (either literally in
config/settings.yaml or via an expanded ``${ENV_VAR}`` that is
present in the environment). Exits 1 with a structured JSON error
otherwise — matches the gateway's design §5.3 envelope so operator
tooling can parse it.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::([^}]*))?\}")


def fail(code: str, message: str, **extras: str) -> None:
    """Emit a structured error envelope and exit(1)."""
    payload = {"error": {"code": code, "message": message, **extras}}
    print(json.dumps(payload), file=sys.stderr)
    sys.exit(1)


def expand(value: object) -> object:
    """Recursively resolve ``${ENV_VAR}`` references in strings.

    When a referenced env var is unset, the placeholder is left intact
    so downstream callers (``str(value).startswith("${")``) can detect
    "not resolved" without a separate sentinel.
    """
    if isinstance(value, str):
        def _replace(match: re.Match) -> str:
            var = match.group(1)
            default = match.group(2)
            return os.environ.get(var, default if default is not None else match.group(0))
        return ENV_PATTERN.sub(_replace, value)
    if isinstance(value, dict):
        return {k: expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [expand(v) for v in value]
    return value


def env_key_for(pattern: str) -> str | None:
    """Extract the ``ENV_VAR`` from a ``${ENV_VAR}`` or ``${ENV_VAR:default}`` string.

    Returns ``None`` when the string is literal.
    """
    match = ENV_PATTERN.fullmatch(pattern.strip())
    if not match:
        return None
    return match.group(1)


try:
    import yaml
except ImportError:
    fail("CONFIG_MISSING", "PyYAML not installed; cannot read config/settings.yaml",
         config_key="pyyaml", expected_in="requirements.txt")


settings_path = Path(os.environ.get("LOHI_ROOT", ".")) / "config" / "settings.yaml"
try:
    raw = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
except FileNotFoundError:
    fail(
        "CONFIG_MISSING",
        f"config/settings.yaml not found (looked at {settings_path}). "
        f"Run the launcher from the repo root, or set LOHI_ROOT.",
        config_key="settings.yaml",
        expected_in=str(settings_path),
    )
except Exception as exc:  # pragma: no cover - defensive
    fail("CONFIG_INVALID", f"failed to parse {settings_path}: {exc}",
         config_key="settings.yaml", expected_in=str(settings_path))


research = raw.get("research") or {}
if not isinstance(research, dict):
    fail("CONFIG_MISSING", "settings.yaml is missing the 'research:' block",
         config_key="research", expected_in="config/settings.yaml")

# Determine whether offline mode is active — offline disables the
# cloud-LLM requirements entirely (Req 9.4).
offline_flag = research.get("offline_mode", False)
if isinstance(offline_flag, str):
    offline_env = env_key_for(offline_flag)
    resolved = os.environ.get(offline_env, "").lower() if offline_env else offline_flag.lower()
    offline = resolved == "true"
else:
    offline = bool(offline_flag)

# Keys that matter for the default cloud path. Each entry is:
#   (description, dotted config path, required_unless_offline)
REQUIRED_CLOUD_KEYS = [
    ("chat LLM api key",    "providers.chat.api_key",    True),
    ("judge LLM api key",   "providers.judge.api_key",   True),
]


def walk(dct: dict, dotted: str) -> object:
    cur: object = dct
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


for description, dotted, required_unless_offline in REQUIRED_CLOUD_KEYS:
    if offline and required_unless_offline:
        continue
    raw_value = walk(research, dotted)
    if raw_value is None or (isinstance(raw_value, str) and raw_value.strip() == ""):
        # Dig for a likely env var name so the hint is actionable.
        env_hint = None
        if isinstance(raw_value, str):
            env_hint = env_key_for(raw_value)
        message = (
            f"research.{dotted} is missing or blank in config/settings.yaml. "
            f"Set it (or export the referenced env var) before starting."
        )
        extras = {"config_key": f"research.{dotted}", "expected_in": "config/settings.yaml"}
        if env_hint:
            extras["env_var"] = env_hint
            extras["expected_in_env"] = ".env.research"
        fail("CONFIG_MISSING", message, **extras)
        break

    # When the value is an unresolved ``${ENV_VAR}`` pattern, the
    # env var is unset — flag it as a missing key (Req 7.6).
    if isinstance(raw_value, str):
        env_var = env_key_for(raw_value)
        if env_var and os.environ.get(env_var) is None:
            fail(
                "CONFIG_MISSING",
                f"research.{dotted} references ${{{env_var}}} but the env var "
                f"is not set. Add it to .env.research.",
                config_key=f"research.{dotted}",
                env_var=env_var,
                expected_in=".env.research",
            )
            break

print("preflight ok", file=sys.stdout)
PYEOF
)"; then
    # Helper emitted structured JSON to stderr and exited non-zero.
    echo "$preflight_output" 1>&2
    return 1
  fi

  log "Pre-flight config check passed"
  return 0
}

# ─── Step 3: Offline-mode Ollama pull ────────────────────────────────────────
maybe_pull_ollama_model() {
  if [ "${LOHI_RESEARCH_OFFLINE:-false}" != "true" ]; then
    return 0
  fi

  local model="${LOHI_RESEARCH_OLLAMA_MODEL:-$DEFAULT_OLLAMA_MODEL}"
  echo ""
  echo -e "${BOLD}Offline mode — ensuring Ollama model '$model' is present...${NC}"
  if ! command -v ollama >/dev/null 2>&1; then
    warn "ollama CLI not found on PATH; skipping pull. Install Ollama or start the 'offline' docker-compose profile."
    return 0
  fi
  if ollama list 2>/dev/null | awk '{print $1}' | grep -qx "$model"; then
    log "Ollama model '$model' already present"
    return 0
  fi
  if ollama pull "$model"; then
    log "Ollama model '$model' ready"
  else
    warn "ollama pull '$model' failed — workers will still start but offline runs may fail until the model is available"
  fi
}

# ─── Step 4: Data directories ────────────────────────────────────────────────
ensure_data_dirs() {
  echo ""
  echo -e "${BOLD}Ensuring data/research directories exist...${NC}"
  mkdir -p "$ROOT_DIR/data/research/chroma"
  mkdir -p "$ROOT_DIR/data/research/uploads"
  mkdir -p "$ROOT_DIR/data/research/snapshots"
  log "data/research/{chroma,uploads,snapshots} ready"
}

# ─── Step 5: Delegate to start.sh for gateway + frontend ─────────────────────
start_base_stack() {
  echo ""
  echo -e "${BOLD}Starting gateway + frontend via ./start.sh...${NC}"
  if [ ! -x "$ROOT_DIR/start.sh" ]; then
    warn "./start.sh is not executable; attempting ``bash start.sh`` as fallback"
    bash "$ROOT_DIR/start.sh"
  else
    "$ROOT_DIR/start.sh"
  fi
}

# ─── Step 6: Spawn supervised workers ────────────────────────────────────────
start_worker() {
  local name="$1"
  local module="$2"
  local logfile="$3"

  echo ""
  echo -e "${BOLD}Starting research-${name}...${NC}"

  # ``nohup`` + ``&`` so the worker outlives the launcher; redirect
  # stdout+stderr to the log file so operators can ``tail -f`` it.
  nohup "$PYTHON_BIN" -m "$module" \
    > "$logfile" 2>&1 &
  local pid=$!
  sleep 0.3
  if kill -0 "$pid" 2>/dev/null; then
    log "research-${name} PID: $pid (log: ${logfile##$ROOT_DIR/})"
    echo "$pid" >> "$PID_FILE"
  else
    warn "research-${name} exited during startup — check ${logfile##$ROOT_DIR/}"
  fi
}

start_research_workers() {
  start_worker "orchestrator" "src.research.workers.orchestrator" "$ORCH_LOG"
  start_worker "indexer"      "src.research.workers.indexer"      "$INDEX_LOG"
  start_worker "snapshotter"  "src.research.workers.snapshotter"  "$SNAP_LOG"
}

# ─── Stop mode ───────────────────────────────────────────────────────────────
stop_all() {
  banner
  echo -e "${YELLOW}${BOLD}Stopping Lohi-Research...${NC}"
  echo ""

  if [ -f "$PID_FILE" ]; then
    while read -r pid; do
      if kill -0 "$pid" 2>/dev/null; then
        kill -TERM "$pid" 2>/dev/null || true
        # Give workers a couple of seconds to drain on SIGTERM before
        # escalating to SIGKILL.
        sleep 0.3
        if kill -0 "$pid" 2>/dev/null; then
          kill -9 "$pid" 2>/dev/null || true
        fi
        log "Killed research worker PID $pid"
      fi
    done < "$PID_FILE"
    rm -f "$PID_FILE"
  else
    warn "No PID file at ${PID_FILE##$ROOT_DIR/}; skipping worker stop"
  fi

  # Also stop the base stack started by ./start.sh.
  if [ -x "$ROOT_DIR/start.sh" ]; then
    "$ROOT_DIR/start.sh" stop || true
  fi

  log "Lohi-Research stopped"
  exit 0
}

# ─── Main entry ──────────────────────────────────────────────────────────────

case "${1:-}" in
  stop)
    stop_all
    ;;
  preflight)
    load_env_files
    if preflight; then
      exit 0
    else
      exit 1
    fi
    ;;
  "")
    banner
    mkdir -p "$LOG_DIR"

    # Fresh PID file per launcher invocation.
    : > "$PID_FILE"

    load_env_files
    if ! preflight; then
      err "Pre-flight check failed; not starting services."
      exit 1
    fi
    maybe_pull_ollama_model
    ensure_data_dirs
    start_base_stack
    start_research_workers

    echo ""
    echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}${BOLD}║         Lohi-Research is running          ║${NC}"
    echo -e "${CYAN}${BOLD}╠══════════════════════════════════════════╣${NC}"
    echo -e "${CYAN}║${NC}  Gateway   →  ${GREEN}http://localhost:8000${NC}       ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}  Frontend  →  ${GREEN}http://localhost:3000${NC}       ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}  Health    →  ${GREEN}/api/v2/research/health${NC}     ${CYAN}║${NC}"
    echo -e "${CYAN}${BOLD}╠══════════════════════════════════════════╣${NC}"
    echo -e "${CYAN}║${NC}  Logs: ${YELLOW}logs/research-*.log${NC}               ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}  Stop: ${YELLOW}./start-research.sh stop${NC}          ${CYAN}║${NC}"
    echo -e "${CYAN}${BOLD}╚══════════════════════════════════════════╝${NC}"
    echo ""
    ;;
  *)
    err "Unknown command: $1"
    echo "Usage: $0 [stop|preflight]" 1>&2
    exit 2
    ;;
esac
