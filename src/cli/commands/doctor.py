"""lohi doctor — Check system dependencies and report issues."""

from __future__ import annotations

from src.cli import console
from src.cli.system import check_all_dependencies, check_required_ports, detect_os


def run_doctor() -> int:
    """Run the doctor command — checks all dependencies and ports."""
    console.header("LOHI-TRADE Doctor")

    os_name = detect_os()
    console.success(f"Operating system: {os_name}")

    # ── Check Dependencies ───────────────────────────────────────────────────
    console.phase("Checking system dependencies...")

    deps = check_all_dependencies()
    all_ok = True

    for dep in deps:
        if dep.installed and dep.install_hint is None:
            console.success(f"{dep.name}: {dep.current_version or 'OK'}")
        elif dep.installed and dep.install_hint:
            console.warn(f"{dep.name}: {dep.current_version} — {dep.install_hint}")
            all_ok = False
        else:
            console.error(f"{dep.name}: not found")
            if dep.install_hint:
                console.info(f"Install: {dep.install_hint}")
            all_ok = False

    # ── Check Ports ──────────────────────────────────────────────────────────
    console.phase("Checking port availability...")

    ports = check_required_ports()
    for port_check in ports:
        if not port_check.in_use:
            console.success(f"Port {port_check.port} ({port_check.service_name}): available")
        else:
            process_info = ""
            if port_check.process_name:
                process_info = f" by {port_check.process_name}"
                if port_check.pid:
                    process_info += f" (PID {port_check.pid})"
            console.warn(
                f"Port {port_check.port} ({port_check.service_name}): in use{process_info}"
            )

    # ── Summary ──────────────────────────────────────────────────────────────
    if all_ok:
        console.done("All dependencies satisfied. Ready to run: lohi setup")
        return 0
    else:
        console.error("Some dependencies need attention. Fix the issues above and re-run: lohi doctor")
        return 1
