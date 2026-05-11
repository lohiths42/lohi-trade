"""lohi status — Show service health and configuration status."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from src.cli import console


def run_status() -> int:
    """Show service health and configuration status."""
    console.header("LOHI-TRADE Status")

    # ── Check backend health ─────────────────────────────────────────────────
    console.phase("Backend gateway (http://localhost:8000)")

    backend_ok = _check_url("http://localhost:8000/api/health")
    if backend_ok:
        console.success("Backend: running")
    else:
        console.error("Backend: not responding")
        console.info("Start with: lohi start")

    # ── Check frontend ───────────────────────────────────────────────────────
    console.phase("Frontend (http://localhost:3000)")

    frontend_ok = _check_url("http://localhost:3000")
    if frontend_ok:
        console.success("Frontend: running")
    else:
        console.warn("Frontend: not responding")

    # ── Check service configuration ──────────────────────────────────────────
    if backend_ok:
        console.phase("Service configuration")
        _show_service_health()

    # ── Docker containers ────────────────────────────────────────────────────
    console.phase("Docker infrastructure")

    import subprocess

    try:
        result = subprocess.run(
            ["docker", "compose", "ps", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            # Parse JSON lines
            for line in result.stdout.strip().split("\n"):
                try:
                    container = json.loads(line)
                    name = container.get("Name", container.get("Service", "unknown"))
                    state = container.get("State", "unknown")
                    health = container.get("Health", "")
                    status_str = state
                    if health:
                        status_str += f" ({health})"
                    if state == "running":
                        console.success(f"{name}: {status_str}")
                    else:
                        console.warn(f"{name}: {status_str}")
                except json.JSONDecodeError:
                    pass
        else:
            console.warn("No Docker containers found")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        console.warn("Docker not available")

    print()
    return 0


def _check_url(url: str) -> bool:
    """Check if a URL responds with 200."""
    try:
        req = urllib.request.urlopen(url, timeout=3)
        return req.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _show_service_health() -> None:
    """Fetch and display service health from the backend."""
    try:
        req = urllib.request.urlopen(
            "http://localhost:8000/api/health/services", timeout=5,
        )
        data = json.loads(req.read().decode())

        services = data.get("services", [])
        setup_complete = data.get("setup_complete", False)

        if setup_complete:
            console.success("Setup: complete")
        else:
            console.warn("Setup: not completed (run the wizard at /setup/integrations)")

        for svc in services:
            name = svc.get("name", svc.get("group_id", "unknown"))
            status = svc.get("status", "unknown")
            required = svc.get("required", False)

            if status == "configured":
                console.success(f"{name}: configured")
            elif status == "skipped":
                console.warn(f"{name}: skipped")
            elif status == "error":
                console.error(f"{name}: error")
            else:
                label = "required" if required else "optional"
                console.info(f"{name}: not configured ({label})")

    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        console.warn("Could not fetch service health (backend may not be running)")
