"""lohi stop — Stop all running LOHI-TRADE services."""

from __future__ import annotations

import os
import signal
import subprocess
import time

from src.cli import console
from src.cli.system import _run_cmd, find_project_root


def run_stop() -> int:
    """Stop all running services."""
    console.header("LOHI-TRADE Stop")

    project_root = find_project_root()
    if project_root:
        os.chdir(project_root)

    # ── Kill backend process ─────────────────────────────────────────────────
    console.phase("Stopping backend gateway (port 8000)...")
    _kill_port(8000, "Backend gateway")

    # ── Kill frontend process ────────────────────────────────────────────────
    console.phase("Stopping frontend dev server (port 3000)...")
    _kill_port(3000, "Frontend dev server")

    # ── Stop Docker containers ───────────────────────────────────────────────
    console.phase("Stopping Docker containers...")
    try:
        result = subprocess.run(
            ["docker", "compose", "down"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            console.success("Docker containers stopped")
        else:
            console.warn("Docker compose down returned non-zero")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        console.warn("Could not stop Docker containers")

    console.done("All services stopped.")
    return 0


def _kill_port(port: int, label: str) -> None:
    """Kill ALL processes using a specific port — SIGTERM then SIGKILL."""
    output = _run_cmd(["lsof", "-ti", f":{port}"])
    if not output:
        console.info(f"{label}: not running")
        return

    pids = set()
    for pid_str in output.strip().split("\n"):
        try:
            pids.add(int(pid_str.strip()))
        except ValueError:
            pass

    if not pids:
        console.info(f"{label}: not running")
        return

    # First try SIGTERM
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass

    # Wait a moment for graceful shutdown
    time.sleep(1)

    # Check if still running, force kill if needed
    for pid in pids:
        try:
            os.kill(pid, 0)  # Check if still alive
            os.kill(pid, signal.SIGKILL)  # Force kill
        except OSError:
            pass  # Already dead

    console.success(f"{label}: stopped (PIDs: {', '.join(str(p) for p in pids)})")
