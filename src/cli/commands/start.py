"""lohi start — Start all LOHI-TRADE services."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from argparse import Namespace
from pathlib import Path

from src.cli import console
from src.cli.system import find_project_root


def run_start(args: Namespace) -> int:
    """Start all services (assumes setup already done)."""
    console.header("LOHI-TRADE Start")

    project_root = find_project_root()
    if not project_root:
        console.error("Cannot find LOHI-TRADE project root.")
        console.info("Run this command from within the project directory.")
        return 1

    os.chdir(project_root)

    # Clear any stale services before starting fresh.
    _kill_port(8000, "Backend gateway")
    if not args.backend_only:
        _kill_port(3000, "Frontend dev server")

    # ── Start Docker ─────────────────────────────────────────────────────────
    console.phase("Starting Docker infrastructure...")
    try:
        result = subprocess.run(
            ["docker", "compose", "up", "-d", "postgres", "redis"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            console.error("Failed to start Docker infrastructure")
            if result.stderr:
                console.info(result.stderr.strip().splitlines()[-1])
            return 1
        console.success("Docker containers started")
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        console.error(f"Failed to start Docker: {e}")
        return 1

    # ── Start Backend ────────────────────────────────────────────────────────
    console.phase("Starting backend gateway...")

    venv_path = Path("lohi_trade_venv")
    if venv_path.exists():
        if sys.platform == "win32":
            python_path = str(venv_path.resolve() / "Scripts" / "python")
        else:
            python_path = str(venv_path.resolve() / "bin" / "python")
    else:
        # Use current Python environment
        python_path = sys.executable

    subprocess.Popen(
        [python_path, "-m", "uvicorn", "app.main:socket_app", "--host", "0.0.0.0", "--port", "8000", "--reload"],
        cwd="backend-gateway",
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    console.success("Backend gateway starting on http://localhost:8000")

    # ── Start Frontend ───────────────────────────────────────────────────────
    if not args.backend_only:
        console.phase("Starting frontend dev server...")

        frontend_dir = Path("Lohi-TRADE Web App Design")
        if not frontend_dir.exists():
            console.warn("Frontend directory not found. Skipping.")
        else:
            subprocess.Popen(
                ["npx", "vite", "--port", "3000", "--host"],
                cwd=str(frontend_dir),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            console.success("Frontend starting on http://localhost:3000")

    console.done("All services started!")
    console.info("  • Backend:    http://localhost:8000")
    if not args.backend_only:
        console.info("  • Frontend:   http://localhost:3000")
    console.info("  • PostgreSQL: localhost:5432")
    console.info("  • Redis:      localhost:6379")
    print()
    console.info("To stop: lohi stop")
    print()

    return 0


def _kill_port(port: int, label: str) -> None:
    """Stop any process listening on a port before launching services."""
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
