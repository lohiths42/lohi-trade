"""lohi setup — Full bootstrap of the LOHI-TRADE stack."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import webbrowser
from argparse import Namespace
from pathlib import Path

from src.cli import console
from src.cli.system import (
    check_all_dependencies,
    check_required_ports,
    detect_os,
    find_project_root,
)


def run_setup(args: Namespace) -> int:
    """Run the full setup flow."""
    console.header("LOHI-TRADE Setup")

    # ── Find project root ────────────────────────────────────────────────────
    project_root = find_project_root()
    if not project_root:
        console.error("Cannot find LOHI-TRADE project root.")
        console.info("Run this command from within the Lohi-Trade-OpenSource directory,")
        console.info("or from any subdirectory of it.")
        return 1

    os.chdir(project_root)
    console.success(f"Project root: {project_root}")

    # ── Phase 1: Check dependencies ──────────────────────────────────────────
    console.phase("Checking system dependencies...")

    deps = check_all_dependencies()
    missing = [d for d in deps if not d.installed or d.install_hint]

    for dep in deps:
        if dep.installed and dep.install_hint is None:
            console.success(f"{dep.name}: {dep.current_version or 'OK'}")
        elif dep.installed and dep.install_hint:
            console.warn(f"{dep.name}: {dep.install_hint}")
        else:
            console.error(f"{dep.name}: not found")
            if dep.install_hint:
                console.info(f"Install: {dep.install_hint}")

    if missing:
        console.error(f"{len(missing)} dependency issue(s). Fix them and re-run: lohi setup")
        return 1

    # If a previous run left the frontend/backend alive, clear those ports so
    # setup can be re-run without manual cleanup.
    _kill_port(8000, "Backend gateway")
    _kill_port(3000, "Frontend dev server")

    # ── Phase 2: Check ports ─────────────────────────────────────────────────
    console.phase("Checking port availability...")

    ports_to_check = check_required_ports()
    # Filter based on what we're actually starting
    if args.skip_docker:
        ports_to_check = [p for p in ports_to_check if p.port not in (5432, 6379)]
    if args.skip_frontend:
        ports_to_check = [p for p in ports_to_check if p.port != 3000]

    # Docker-owned ports (5432, 6379) are fine — they're our own containers
    conflicts = []
    for p in ports_to_check:
        if not p.in_use:
            continue
        # If Docker is using ports 5432/6379, that's our infra already running — skip
        if p.port in (5432, 6379) and p.process_name and "docker" in p.process_name.lower():
            console.success(f"Port {p.port} ({p.service_name}): already running (Docker)")
            continue
        conflicts.append(p)

    if conflicts:
        for p in conflicts:
            process_info = f" by {p.process_name}" if p.process_name else ""
            console.error(f"Port {p.port} ({p.service_name}) is in use{process_info}")
            if p.pid:
                console.info(f"Try: kill {p.pid}")
        console.error("Free the ports above and re-run: lohi setup")
        return 1

    if not conflicts:
        console.success("All required ports are available")

    # ── Phase 3: Python virtual environment ──────────────────────────────────
    console.phase("Setting up Python environment...")

    venv_path = Path("lohi_trade_venv")

    # Determine pip/python path — use venv if it exists, otherwise current env
    if venv_path.exists():
        if sys.platform == "win32":
            pip_path = str(venv_path.resolve() / "Scripts" / "pip")
            python_path = str(venv_path.resolve() / "Scripts" / "python")
        else:
            pip_path = str(venv_path.resolve() / "bin" / "pip")
            python_path = str(venv_path.resolve() / "bin" / "python")
        console.success("Using backend venv")
    else:
        # No separate venv — use the current Python environment
        python_path = sys.executable
        pip_path = python_path.replace("python", "pip")
        console.success(f"Using current environment")

    _run([python_path, "-m", "pip", "install", "--quiet", "--upgrade", "pip"], "Upgrading pip")
    _run([python_path, "-m", "pip", "install", "--quiet", "-e", "."], "Installing project dependencies")

    try:
        result = subprocess.run(
            [python_path, "-m", "spacy", "download", "en_core_web_sm"],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode == 0:
            console.success("spaCy model downloaded: en_core_web_sm")
        else:
            console.warn("spaCy model download skipped or failed; NER features will degrade gracefully")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        console.warn("spaCy model download skipped or failed; NER features will degrade gracefully")

    console.success("Project dependencies installed")

    # ── Phase 4: Frontend dependencies ───────────────────────────────────────
    if not args.skip_frontend:
        console.phase("Installing frontend dependencies...")

        frontend_dir = Path("Lohi-TRADE Web App Design")
        if not frontend_dir.exists():
            console.error("Frontend directory not found: Lohi-TRADE Web App Design/")
            return 1

        lock_file = frontend_dir / "package-lock.json"
        npm_cmd = "ci" if lock_file.exists() else "install"
        _run(
            ["npm", npm_cmd, "--legacy-peer-deps"],
            "Installing frontend packages",
            cwd=str(frontend_dir),
        )
        console.success("Frontend dependencies installed")

    # ── Phase 5: Docker infrastructure ───────────────────────────────────────
    if not args.skip_docker:
        console.phase("Starting Docker infrastructure...")

        # Check if containers are already running
        already_running = _check_docker_running()
        if already_running:
            console.success("Docker containers already running")
        else:
            _run(
                ["docker", "compose", "up", "-d", "postgres", "redis"],
                "Starting PostgreSQL and Redis",
            )

            # Wait for healthy containers
            console.info("Waiting for containers to be healthy...")
            if not _wait_healthy("postgres", timeout=60):
                console.error("PostgreSQL did not become healthy within 60s")
                console.info("Check logs: docker compose logs postgres")
                return 1
            console.success("PostgreSQL: healthy")

            if not _wait_healthy("redis", timeout=60):
                console.error("Redis did not become healthy within 60s")
                console.info("Check logs: docker compose logs redis")
                return 1
            console.success("Redis: healthy")

    # ── Phase 6: Start backend ───────────────────────────────────────────────
    console.phase("Starting backend gateway...")

    backend_port = args.backend_port
    _start_background(
        [python_path, "-m", "uvicorn", "app.main:socket_app", "--host", "0.0.0.0", "--port", str(backend_port), "--reload"],
        cwd="backend-gateway",
        label="Backend gateway",
    )

    # Wait for backend to respond
    if _wait_for_url(f"http://localhost:{backend_port}/api/health", timeout=30):
        console.success(f"Backend gateway: running on http://localhost:{backend_port}")
    else:
        console.warn(f"Backend may still be starting. Check: http://localhost:{backend_port}/api/health")

    # ── Phase 7: Start frontend ──────────────────────────────────────────────
    if not args.skip_frontend:
        console.phase("Starting frontend dev server...")

        frontend_port = args.frontend_port
        _start_background(
            ["npx", "vite", "--port", str(frontend_port), "--host"],
            cwd="Lohi-TRADE Web App Design",
            label="Frontend dev server",
        )

        if _wait_for_url(f"http://localhost:{frontend_port}", timeout=20):
            console.success(f"Frontend: running on http://localhost:{frontend_port}")
        else:
            console.warn(f"Frontend may still be starting. Check: http://localhost:{frontend_port}")

    # ── Phase 8: Open browser ────────────────────────────────────────────────
    if not args.no_browser and not args.skip_frontend:
        setup_url = f"http://localhost:{args.frontend_port}/setup/integrations"
        console.phase("Opening browser...")
        try:
            webbrowser.open(setup_url)
            console.success(f"Opened: {setup_url}")
        except Exception:
            console.warn(f"Could not open browser. Visit: {setup_url}")

    # ── Done ─────────────────────────────────────────────────────────────────
    console.done("Setup complete! 🎉")
    console.info("Services running:")
    console.info(f"  • Backend:    http://localhost:{args.backend_port}")
    if not args.skip_frontend:
        console.info(f"  • Frontend:   http://localhost:{args.frontend_port}")
    if not args.skip_docker:
        console.info("  • PostgreSQL: localhost:5432")
        console.info("  • Redis:      localhost:6379")
    print()
    if not args.skip_frontend:
        console.info(f"Setup wizard: http://localhost:{args.frontend_port}/setup/integrations")
    console.info("")
    console.info("To stop all services: lohi stop")
    print()

    return 0


# ── Helpers ──────────────────────────────────────────────────────────────────


def _run(cmd: list[str], description: str, cwd: str | None = None) -> None:
    """Run a command, showing progress and handling errors."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=300,
        )
        if result.returncode != 0:
            console.error(f"{description} failed (exit code {result.returncode})")
            if result.stderr:
                for line in result.stderr.strip().split("\n")[-5:]:
                    console.info(line)
            raise SystemExit(1)
    except subprocess.TimeoutExpired:
        console.error(f"{description} timed out (300s)")
        raise SystemExit(1)
    except FileNotFoundError:
        console.error(f"Command not found: {cmd[0]}")
        raise SystemExit(1)


def _kill_port(port: int, label: str) -> None:
    """Stop any process listening on a port before setup starts services."""
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return

    if result.returncode != 0 or not result.stdout.strip():
        return

    pids: list[int] = []
    for pid_str in result.stdout.strip().splitlines():
        try:
            pids.append(int(pid_str.strip()))
        except ValueError:
            continue

    if not pids:
        return

    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass

    time.sleep(1)

    for pid in pids:
        try:
            os.kill(pid, 0)
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass

    console.success(f"{label}: stopped (PIDs: {', '.join(str(pid) for pid in pids)})")


def _start_background(cmd: list[str], cwd: str, label: str) -> None:
    """Start a process in the background."""
    try:
        subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except FileNotFoundError:
        console.error(f"Cannot start {label}: {cmd[0]} not found")
        raise SystemExit(1)


def _wait_healthy(service: str, timeout: int = 60) -> bool:
    """Wait for a Docker container to become healthy."""
    elapsed = 0
    interval = 2
    while elapsed < timeout:
        try:
            result = subprocess.run(
                ["docker", "compose", "ps", service, "--format", "{{.Health}}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if "healthy" in result.stdout.lower():
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        time.sleep(interval)
        elapsed += interval
    return False


def _wait_for_url(url: str, timeout: int = 30) -> bool:
    """Wait for a URL to respond with 200."""
    import urllib.request
    import urllib.error

    elapsed = 0
    interval = 2
    while elapsed < timeout:
        try:
            req = urllib.request.urlopen(url, timeout=3)
            if req.status == 200:
                return True
        except (urllib.error.URLError, OSError, ValueError):
            pass
        time.sleep(interval)
        elapsed += interval
    return False


def _check_docker_running() -> bool:
    """Check if Docker containers (postgres, redis) are already running."""
    try:
        result = subprocess.run(
            ["docker", "compose", "ps", "--format", "json"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and "running" in result.stdout.lower():
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return False
