#!/usr/bin/env bash
# setup.sh — LOHI-TRADE One-Command Bootstrap
# POSIX-compatible (bash 3.2+), works on macOS + Linux
#
# Usage: ./setup.sh
#
# Phases:
# 1. Detect OS and package manager
# 2. Check system dependencies (Docker, Docker Compose, Node.js 18+, Python 3.11+)
# 3. Report missing deps with platform-specific install commands
# 4. Create Python venv + install backend deps
# 5. Install frontend deps (npm ci)
# 6. Start Docker infrastructure (postgres, redis)
# 7. Wait for healthy containers (60s timeout)
# 8. Start backend gateway (uvicorn)
# 9. Start frontend dev server (vite)
# 10. Open browser to http://localhost:3000/setup/integrations

set -euo pipefail

# ─── Colors ───────────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# ─── Helpers ──────────────────────────────────────────────────────────────────

print_status() {
    printf "${GREEN}✓${NC} %s\n" "$1"
}

print_warning() {
    printf "${YELLOW}⚠${NC} %s\n" "$1"
}

print_error() {
    printf "${RED}✗${NC} %s\n" "$1"
}

print_phase() {
    printf "\n${BLUE}${BOLD}▶ %s${NC}\n" "$1"
}

print_info() {
    printf "  %s\n" "$1"
}

# ─── OS Detection ────────────────────────────────────────────────────────────

detect_os() {
    local uname_s
    uname_s="$(uname -s)"

    case "$uname_s" in
        Darwin)
            echo "macos"
            return
            ;;
        Linux)
            if [ -f /etc/os-release ]; then
                # shellcheck disable=SC1091
                . /etc/os-release
                case "$ID" in
                    ubuntu|debian)
                        echo "ubuntu"
                        return
                        ;;
                    fedora|rhel|centos)
                        echo "fedora"
                        return
                        ;;
                    arch|manjaro)
                        echo "arch"
                        return
                        ;;
                esac
            fi
            ;;
    esac

    echo "unknown"
}

# ─── Dependency Checking ─────────────────────────────────────────────────────

# check_dependency name min_version check_cmd
# Returns 0 if dependency is satisfied, 1 otherwise
check_dependency() {
    local name="$1"
    local min_version="$2"
    local check_cmd="$3"

    # Check if command exists
    if ! command -v "$check_cmd" >/dev/null 2>&1; then
        return 1
    fi

    # Version check based on dependency name
    local version=""
    case "$name" in
        docker)
            version="$(docker --version 2>/dev/null | sed -E 's/.*version ([0-9]+\.[0-9]+).*/\1/' || echo "0.0")"
            ;;
        docker-compose)
            # Try docker compose (v2) first, then docker-compose (v1)
            if docker compose version >/dev/null 2>&1; then
                version="$(docker compose version 2>/dev/null | sed -E 's/.*v?([0-9]+\.[0-9]+).*/\1/' || echo "0.0")"
            elif command -v docker-compose >/dev/null 2>&1; then
                version="$(docker-compose --version 2>/dev/null | sed -E 's/.*version ([0-9]+\.[0-9]+).*/\1/' || echo "0.0")"
            else
                return 1
            fi
            ;;
        node)
            version="$(node --version 2>/dev/null | sed -E 's/v([0-9]+).*/\1/' || echo "0")"
            ;;
        python)
            version="$(python3 --version 2>/dev/null | sed -E 's/Python ([0-9]+\.[0-9]+).*/\1/' || echo "0.0")"
            ;;
    esac

    # Compare versions (major.minor)
    local min_major min_minor cur_major cur_minor
    min_major="$(echo "$min_version" | cut -d. -f1)"
    min_minor="$(echo "$min_version" | cut -d. -f2)"
    cur_major="$(echo "$version" | cut -d. -f1)"
    cur_minor="$(echo "$version" | cut -d. -f2)"

    if [ "$cur_major" -gt "$min_major" ] 2>/dev/null; then
        return 0
    elif [ "$cur_major" -eq "$min_major" ] 2>/dev/null && [ "$cur_minor" -ge "$min_minor" ] 2>/dev/null; then
        return 0
    fi

    return 1
}

# ─── Install Suggestions ─────────────────────────────────────────────────────

suggest_install() {
    local name="$1"
    local os="$2"

    print_error "$name is missing or below minimum version."
    printf "  Install with:\n"

    case "$os" in
        macos)
            case "$name" in
                docker)
                    print_info "brew install --cask docker"
                    print_info "Then open Docker Desktop to complete setup."
                    ;;
                docker-compose)
                    print_info "Docker Compose is included with Docker Desktop."
                    print_info "brew install --cask docker"
                    ;;
                node)
                    print_info "brew install node@18"
                    ;;
                python)
                    print_info "brew install python@3.11"
                    ;;
            esac
            ;;
        ubuntu)
            case "$name" in
                docker)
                    print_info "sudo apt-get update && sudo apt-get install -y docker.io"
                    print_info "sudo systemctl enable --now docker"
                    print_info "sudo usermod -aG docker \$USER"
                    ;;
                docker-compose)
                    print_info "sudo apt-get install -y docker-compose-plugin"
                    ;;
                node)
                    print_info "curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -"
                    print_info "sudo apt-get install -y nodejs"
                    ;;
                python)
                    print_info "sudo apt-get install -y python3.11 python3.11-venv"
                    ;;
            esac
            ;;
        fedora)
            case "$name" in
                docker)
                    print_info "sudo dnf install -y docker"
                    print_info "sudo systemctl enable --now docker"
                    print_info "sudo usermod -aG docker \$USER"
                    ;;
                docker-compose)
                    print_info "sudo dnf install -y docker-compose-plugin"
                    ;;
                node)
                    print_info "sudo dnf install -y nodejs"
                    ;;
                python)
                    print_info "sudo dnf install -y python3.11"
                    ;;
            esac
            ;;
        arch)
            case "$name" in
                docker)
                    print_info "sudo pacman -S docker"
                    print_info "sudo systemctl enable --now docker"
                    print_info "sudo usermod -aG docker \$USER"
                    ;;
                docker-compose)
                    print_info "sudo pacman -S docker-compose"
                    ;;
                node)
                    print_info "sudo pacman -S nodejs npm"
                    ;;
                python)
                    print_info "sudo pacman -S python"
                    ;;
            esac
            ;;
        *)
            print_info "Please install $name manually. See: https://docs.docker.com/get-docker/"
            ;;
    esac
    echo ""
}

# ─── Port Checking ───────────────────────────────────────────────────────────

check_ports() {
    local ports="5432 6379 8000 3000"
    local conflicts=0

    for port in $ports; do
        local pid=""
        local process_name=""

        if command -v lsof >/dev/null 2>&1; then
            pid="$(lsof -ti :"$port" 2>/dev/null | head -1 || true)"
            if [ -n "$pid" ]; then
                process_name="$(ps -p "$pid" -o comm= 2>/dev/null || echo "unknown")"
            fi
        elif command -v ss >/dev/null 2>&1; then
            pid="$(ss -tlnp "sport = :$port" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | head -1 || true)"
            if [ -n "$pid" ]; then
                process_name="$(ps -p "$pid" -o comm= 2>/dev/null || echo "unknown")"
            fi
        elif command -v netstat >/dev/null 2>&1; then
            if netstat -tuln 2>/dev/null | grep -q ":$port "; then
                pid="unknown"
                process_name="unknown"
            fi
        fi

        if [ -n "$pid" ]; then
            print_error "Port $port is already in use by $process_name (PID: $pid)"
            conflicts=$((conflicts + 1))

            case "$port" in
                5432)
                    print_info "This port is needed for PostgreSQL."
                    print_info "Try: sudo kill $pid  OR  sudo systemctl stop postgresql"
                    ;;
                6379)
                    print_info "This port is needed for Redis."
                    print_info "Try: sudo kill $pid  OR  sudo systemctl stop redis"
                    ;;
                8000)
                    print_info "This port is needed for the backend gateway."
                    print_info "Try: kill $pid"
                    ;;
                3000)
                    print_info "This port is needed for the frontend dev server."
                    print_info "Try: kill $pid"
                    ;;
            esac
            echo ""
        fi
    done

    return $conflicts
}

# ─── Wait for Healthy Container ──────────────────────────────────────────────

wait_healthy() {
    local service="$1"
    local timeout="${2:-60}"
    local elapsed=0
    local interval=2

    while [ $elapsed -lt "$timeout" ]; do
        local health
        health="$(docker compose ps "$service" --format '{{.Health}}' 2>/dev/null || echo "")"

        if [ "$health" = "healthy" ]; then
            return 0
        fi

        sleep $interval
        elapsed=$((elapsed + interval))
    done

    # Timeout reached
    print_error "$service did not become healthy within ${timeout}s"
    print_info "Container logs:"
    docker compose logs --tail=20 "$service" 2>/dev/null || true
    print_info ""
    print_info "Troubleshooting:"
    print_info "  - Check if Docker has enough resources (RAM/CPU)"
    print_info "  - Try: docker compose down && docker compose up -d"
    print_info "  - Check logs: docker compose logs $service"
    return 1
}

# ─── Open Browser ─────────────────────────────────────────────────────────────

open_browser() {
    local url="$1"
    local os
    os="$(detect_os)"

    case "$os" in
        macos)
            open "$url" 2>/dev/null || true
            ;;
        *)
            if command -v xdg-open >/dev/null 2>&1; then
                xdg-open "$url" 2>/dev/null || true
            else
                print_warning "Could not open browser automatically."
                print_info "Please open: $url"
            fi
            ;;
    esac
}

# ─── Cleanup on Exit ─────────────────────────────────────────────────────────

cleanup() {
    local exit_code=$?
    if [ $exit_code -ne 0 ]; then
        echo ""
        print_error "Setup encountered an error (exit code: $exit_code)"
        print_info "If you need help, check the troubleshooting section in README.md"
        print_info "or run with: bash -x setup.sh  for debug output."
    fi
}

trap cleanup EXIT

# ─── Main Flow ────────────────────────────────────────────────────────────────

main() {
    echo ""
    printf '%s╔══════════════════════════════════════════╗%s\n' "$BOLD" "$NC"
    printf '%s║     LOHI-TRADE — One-Command Setup      ║%s\n' "$BOLD" "$NC"
    printf '%s╚══════════════════════════════════════════╝%s\n' "$BOLD" "$NC"
    echo ""

    # ── Phase 1: Detect OS ────────────────────────────────────────────────────
    print_phase "Phase 1: Detecting operating system..."

    local os
    os="$(detect_os)"
    print_status "Detected OS: $os"

    if [ "$os" = "unknown" ]; then
        print_warning "Could not detect your OS. Install suggestions may be generic."
    fi

    # ── Phase 2: Check Dependencies ──────────────────────────────────────────
    print_phase "Phase 2: Checking system dependencies..."

    local missing_deps=0

    if check_dependency "docker" "20.0" "docker"; then
        print_status "Docker: OK"
    else
        suggest_install "docker" "$os"
        missing_deps=$((missing_deps + 1))
    fi

    if check_dependency "docker-compose" "2.0" "docker"; then
        print_status "Docker Compose: OK"
    else
        suggest_install "docker-compose" "$os"
        missing_deps=$((missing_deps + 1))
    fi

    if check_dependency "node" "18.0" "node"; then
        print_status "Node.js: OK ($(node --version 2>/dev/null))"
    else
        suggest_install "node" "$os"
        missing_deps=$((missing_deps + 1))
    fi

    if check_dependency "python" "3.11" "python3"; then
        print_status "Python: OK ($(python3 --version 2>/dev/null))"
    else
        suggest_install "python" "$os"
        missing_deps=$((missing_deps + 1))
    fi

    if [ $missing_deps -gt 0 ]; then
        echo ""
        print_error "Missing $missing_deps dependency(ies). Please install them and re-run ./setup.sh"
        exit 1
    fi

    # Check Docker daemon is running
    if ! docker info >/dev/null 2>&1; then
        print_error "Docker daemon is not running."
        case "$os" in
            macos)
                print_info "Please open Docker Desktop and wait for it to start."
                ;;
            *)
                print_info "Try: sudo systemctl start docker"
                ;;
        esac
        exit 1
    fi
    print_status "Docker daemon: running"

    # ── Phase 3: Check Ports ─────────────────────────────────────────────────
    print_phase "Phase 3: Checking port availability..."

    if check_ports; then
        print_status "All required ports are available"
    else
        print_error "Port conflicts detected. Please free the ports above and re-run ./setup.sh"
        exit 1
    fi

    # ── Phase 4: Python Virtual Environment ──────────────────────────────────
    print_phase "Phase 4: Setting up Python virtual environment..."

    if [ ! -d "lohi_trade_venv" ]; then
        python3 -m venv lohi_trade_venv
        print_status "Created virtual environment at lohi_trade_venv"
    else
        print_status "Virtual environment already exists"
    fi

    # Activate venv and install deps
    # shellcheck disable=SC1091
    . lohi_trade_venv/bin/activate

    print_info "Installing backend dependencies..."
    python -m pip install --quiet --upgrade pip
    python -m pip install --quiet -e .
    print_status "Project dependencies installed"

    if python -m spacy download en_core_web_sm >/dev/null 2>&1; then
        print_status "spaCy model downloaded: en_core_web_sm"
    else
        print_warning "spaCy model download skipped or failed; NER features will degrade gracefully"
    fi

    # ── Phase 5: Frontend Dependencies ───────────────────────────────────────
    print_phase "Phase 5: Installing frontend dependencies..."

    if [ -f "Lohi-TRADE Web App Design/package-lock.json" ]; then
        (cd "Lohi-TRADE Web App Design" && npm ci --silent)
    else
        (cd "Lohi-TRADE Web App Design" && npm install --silent)
    fi
    print_status "Frontend dependencies installed"

    # ── Phase 6: Docker Infrastructure ───────────────────────────────────────
    print_phase "Phase 6: Starting Docker infrastructure..."

    docker compose up -d postgres redis
    print_status "Docker containers starting (PostgreSQL, Redis)"

    # ── Phase 7: Wait for Healthy Containers ─────────────────────────────────
    print_phase "Phase 7: Waiting for services to be healthy..."

    if wait_healthy "postgres" 60; then
        print_status "PostgreSQL: healthy"
    else
        exit 1
    fi

    if wait_healthy "redis" 60; then
        print_status "Redis: healthy"
    else
        exit 1
    fi

    # ── Phase 8: Start Backend ───────────────────────────────────────────────
    print_phase "Phase 8: Starting backend gateway..."

    # Kill any existing backend process on port 8000
    if lsof -ti :8000 >/dev/null 2>&1; then
        print_warning "Stopping existing process on port 8000..."
        kill "$(lsof -ti :8000)" 2>/dev/null || true
        sleep 1
    fi

    (
        cd backend-gateway
        python -m uvicorn app.main:socket_app --host 0.0.0.0 --port 8000 --reload > /dev/null 2>&1 &
    )

    # Wait briefly for backend to start
    local backend_ready=0
    local attempts=0
    while [ $attempts -lt 15 ]; do
        if curl -sf http://localhost:8000/api/health >/dev/null 2>&1; then
            backend_ready=1
            break
        fi
        sleep 2
        attempts=$((attempts + 1))
    done

    if [ $backend_ready -eq 1 ]; then
        print_status "Backend gateway: running on http://localhost:8000"
    else
        print_warning "Backend may still be starting. Check: curl http://localhost:8000/api/health"
    fi

    # ── Phase 9: Start Frontend ──────────────────────────────────────────────
    print_phase "Phase 9: Starting frontend dev server..."

    (
        cd "Lohi-TRADE Web App Design"
        npx vite --port 3000 --host > /dev/null 2>&1 &
    )

    # Wait briefly for frontend to start
    local frontend_ready=0
    attempts=0
    while [ $attempts -lt 10 ]; do
        if curl -sf http://localhost:3000 >/dev/null 2>&1; then
            frontend_ready=1
            break
        fi
        sleep 2
        attempts=$((attempts + 1))
    done

    if [ $frontend_ready -eq 1 ]; then
        print_status "Frontend: running on http://localhost:3000"
    else
        print_warning "Frontend may still be starting. Check: http://localhost:3000"
    fi

    # ── Phase 10: Open Browser ───────────────────────────────────────────────
    print_phase "Phase 10: Opening browser..."

    local setup_url="http://localhost:3000/setup/integrations"
    open_browser "$setup_url"

    # ── Done ─────────────────────────────────────────────────────────────────
    echo ""
    printf '%s%s╔══════════════════════════════════════════╗%s\n' "$GREEN" "$BOLD" "$NC"
    printf '%s%s║         Setup Complete! 🎉               ║%s\n' "$GREEN" "$BOLD" "$NC"
    printf '%s%s╚══════════════════════════════════════════╝%s\n' "$GREEN" "$BOLD" "$NC"
    echo ""
    print_info "Services running:"
    print_info "  • Frontend:   http://localhost:3000"
    print_info "  • Backend:    http://localhost:8000"
    print_info "  • PostgreSQL: localhost:5432"
    print_info "  • Redis:      localhost:6379"
    echo ""
    print_info "Setup wizard: $setup_url"
    print_info ""
    print_info "To stop all services:"
    print_info "  docker compose down"
    print_info "  kill \$(lsof -ti :8000) 2>/dev/null  # backend"
    print_info "  kill \$(lsof -ti :3000) 2>/dev/null  # frontend"
    echo ""
}

# Run main
main "$@"
