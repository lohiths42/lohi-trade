"""System detection and dependency checking utilities."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass


@dataclass
class DependencyCheck:
    """Result of checking a system dependency."""

    name: str
    required_version: str
    installed: bool
    current_version: str | None = None
    install_hint: str | None = None


@dataclass
class PortCheck:
    """Result of checking a port."""

    port: int
    service_name: str
    in_use: bool
    pid: int | None = None
    process_name: str | None = None


def detect_os() -> str:
    """Detect the operating system. Returns: macos, ubuntu, fedora, arch, or unknown."""
    system = platform.system()
    if system == "Darwin":
        return "macos"
    if system == "Linux":
        try:
            with open("/etc/os-release") as f:
                content = f.read().lower()
            if "ubuntu" in content or "debian" in content:
                return "ubuntu"
            if "fedora" in content or "rhel" in content or "centos" in content:
                return "fedora"
            if "arch" in content or "manjaro" in content:
                return "arch"
        except FileNotFoundError:
            pass
    return "unknown"


def get_install_hint(dep_name: str, os_name: str) -> str:
    """Get platform-specific install command for a dependency."""
    hints = {
        "docker": {
            "macos": "brew install --cask docker",
            "ubuntu": "sudo apt-get install -y docker.io && sudo systemctl enable --now docker",
            "fedora": "sudo dnf install -y docker && sudo systemctl enable --now docker",
            "arch": "sudo pacman -S docker && sudo systemctl enable --now docker",
        },
        "docker-compose": {
            "macos": "Included with Docker Desktop (brew install --cask docker)",
            "ubuntu": "sudo apt-get install -y docker-compose-plugin",
            "fedora": "sudo dnf install -y docker-compose-plugin",
            "arch": "sudo pacman -S docker-compose",
        },
        "node": {
            "macos": "brew install node@18",
            "ubuntu": "curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash - && sudo apt-get install -y nodejs",
            "fedora": "sudo dnf install -y nodejs",
            "arch": "sudo pacman -S nodejs npm",
        },
        "python": {
            "macos": "brew install python@3.11",
            "ubuntu": "sudo apt-get install -y python3.11 python3.11-venv",
            "fedora": "sudo dnf install -y python3.11",
            "arch": "sudo pacman -S python",
        },
        "git": {
            "macos": "brew install git",
            "ubuntu": "sudo apt-get install -y git",
            "fedora": "sudo dnf install -y git",
            "arch": "sudo pacman -S git",
        },
        "curl": {
            "macos": "Included with macOS (or brew install curl)",
            "ubuntu": "sudo apt-get install -y curl",
            "fedora": "sudo dnf install -y curl",
            "arch": "sudo pacman -S curl",
        },
        "lsof": {
            "macos": "Included with macOS",
            "ubuntu": "sudo apt-get install -y lsof",
            "fedora": "sudo dnf install -y lsof",
            "arch": "sudo pacman -S lsof",
        },
        "ta-lib": {
            "macos": "brew install ta-lib",
            "ubuntu": "wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz && tar -xzf ta-lib-0.4.0-src.tar.gz && cd ta-lib/ && ./configure --prefix=/usr && make && sudo make install",
            "fedora": "sudo dnf install ta-lib",
            "arch": "sudo pacman -S ta-lib",
        },
    }
    return hints.get(dep_name, {}).get(os_name, f"Please install {dep_name} manually")


def _run_cmd(cmd: list[str], timeout: int = 10) -> str | None:
    """Run a command and return stdout, or None on failure."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def check_docker() -> DependencyCheck:
    """Check if Docker is installed and running."""
    if not shutil.which("docker"):
        return DependencyCheck(
            name="Docker",
            required_version="20.0+",
            installed=False,
            install_hint=get_install_hint("docker", detect_os()),
        )

    version_output = _run_cmd(["docker", "--version"])
    if not version_output:
        return DependencyCheck(
            name="Docker",
            required_version="20.0+",
            installed=False,
            install_hint="Docker is installed but not responding. Is the daemon running?",
        )

    # Extract version number
    import re

    match = re.search(r"(\d+\.\d+)", version_output)
    version = match.group(1) if match else "unknown"

    # Auto‑start Docker Desktop on macOS if daemon not running
    if sys.platform == "darwin":
        # Try to open Docker app silently; Docker Desktop will start the daemon.
        try:
            subprocess.run(
                ["open", "-a", "Docker"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception:
            pass
        # Give Docker a few seconds to start up before checking again
        time.sleep(5)
        daemon_check = _run_cmd(["docker", "info"], timeout=10)
    else:
        daemon_check = _run_cmd(["docker", "info"], timeout=10)
    if daemon_check is None:
        return DependencyCheck(
            name="Docker",
            required_version="20.0+",
            installed=True,
            current_version=version,
            install_hint="Docker daemon is not running. Start Docker Desktop or run: sudo systemctl start docker",
        )

    return DependencyCheck(
        name="Docker",
        required_version="20.0+",
        installed=True,
        current_version=version,
    )


def check_docker_compose() -> DependencyCheck:
    """Check if Docker Compose is available."""
    # Try docker compose (v2) first
    output = _run_cmd(["docker", "compose", "version"])
    if output:
        import re

        match = re.search(r"v?(\d+\.\d+)", output)
        version = match.group(1) if match else "unknown"
        return DependencyCheck(
            name="Docker Compose",
            required_version="2.0+",
            installed=True,
            current_version=version,
        )

    # Try docker-compose (v1)
    if shutil.which("docker-compose"):
        output = _run_cmd(["docker-compose", "--version"])
        if output:
            import re

            match = re.search(r"(\d+\.\d+)", output)
            version = match.group(1) if match else "unknown"
            return DependencyCheck(
                name="Docker Compose",
                required_version="2.0+",
                installed=True,
                current_version=version,
            )

    return DependencyCheck(
        name="Docker Compose",
        required_version="2.0+",
        installed=False,
        install_hint=get_install_hint("docker-compose", detect_os()),
    )


def check_node() -> DependencyCheck:
    """Check if Node.js 18+ is installed."""
    if not shutil.which("node"):
        return DependencyCheck(
            name="Node.js",
            required_version="18.0+",
            installed=False,
            install_hint=get_install_hint("node", detect_os()),
        )

    output = _run_cmd(["node", "--version"])
    if not output:
        return DependencyCheck(
            name="Node.js",
            required_version="18.0+",
            installed=False,
            install_hint=get_install_hint("node", detect_os()),
        )

    # Parse version (e.g., "v18.17.0" → 18)
    import re

    match = re.search(r"v?(\d+)", output)
    major = int(match.group(1)) if match else 0

    if major < 18:
        return DependencyCheck(
            name="Node.js",
            required_version="18.0+",
            installed=True,
            current_version=output.lstrip("v"),
            install_hint=f"Node.js {output} is too old. Need 18+. {get_install_hint('node', detect_os())}",
        )

    return DependencyCheck(
        name="Node.js",
        required_version="18.0+",
        installed=True,
        current_version=output.lstrip("v"),
    )


def check_python() -> DependencyCheck:
    """Check Python version (we're already running in Python, so just check version)."""
    import sys

    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info < (3, 11):
        return DependencyCheck(
            name="Python",
            required_version="3.11+",
            installed=True,
            current_version=version,
            install_hint=f"Python {version} is too old. Need 3.11+. {get_install_hint('python', detect_os())}",
        )
    return DependencyCheck(
        name="Python",
        required_version="3.11+",
        installed=True,
        current_version=version,
    )


def check_binary(name: str, display_name: str, required_version: str = "any") -> DependencyCheck:
    """Generic check for a binary in PATH."""
    if not shutil.which(name):
        return DependencyCheck(
            name=display_name,
            required_version=required_version,
            installed=False,
            install_hint=get_install_hint(name, detect_os()),
        )
    return DependencyCheck(
        name=display_name,
        required_version=required_version,
        installed=True,
        current_version="installed",
    )


def check_all_dependencies() -> list[DependencyCheck]:
    """Check all required system dependencies."""
    return [
        check_docker(),
        check_docker_compose(),
        check_node(),
        check_python(),
        check_binary("git", "Git"),
        check_binary("curl", "Curl"),
        check_binary("lsof", "lsof"),
    ]


def check_port(port: int, service_name: str) -> PortCheck:
    """Check if a port is available by checking for LISTENING processes."""
    # Use lsof to check if something is LISTENING on this port
    output = _run_cmd(["lsof", "-ti", f":{port}", "-sTCP:LISTEN"])
    if output:
        try:
            pid = int(output.split("\n")[0])
            ps_output = _run_cmd(["ps", "-p", str(pid), "-o", "comm="])
            return PortCheck(
                port=port,
                service_name=service_name,
                in_use=True,
                pid=pid,
                process_name=ps_output,
            )
        except (ValueError, IndexError):
            pass

    return PortCheck(port=port, service_name=service_name, in_use=False)


def _find_port_process(port: int) -> tuple[int | None, str | None]:
    """Find the PID and process name LISTENING on a port (not clients)."""
    # Use -sTCP:LISTEN to only find servers, not client connections
    output = _run_cmd(["lsof", "-ti", f":{port}", "-sTCP:LISTEN"])
    if output:
        try:
            pid = int(output.split("\n")[0])
            ps_output = _run_cmd(["ps", "-p", str(pid), "-o", "comm="])
            return pid, ps_output
        except (ValueError, IndexError):
            pass
    return None, None


def check_required_ports() -> list[PortCheck]:
    """Check all required ports."""
    ports = [
        (5432, "PostgreSQL"),
        (6379, "Redis"),
        (8000, "Backend Gateway"),
        (3000, "Frontend Dev Server"),
    ]
    return [check_port(port, name) for port, name in ports]


def find_project_root() -> str | None:
    """Find the LOHI-TRADE project root by looking for docker-compose.yml + backend-gateway/.

    Searches:
    1. Current directory
    2. Parent directories (up to 5 levels)
    3. Immediate subdirectories of current directory (e.g., Lohi-Trade-OpenSource/)
    """

    def _is_project_root(path: str) -> bool:
        return os.path.exists(os.path.join(path, "docker-compose.yml")) and os.path.exists(
            os.path.join(path, "backend-gateway")
        )

    # Check current directory and parents
    current = os.getcwd()
    for _ in range(5):
        if _is_project_root(current):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent

    # Check immediate subdirectories of cwd
    cwd = os.getcwd()
    try:
        for entry in os.listdir(cwd):
            candidate = os.path.join(cwd, entry)
            if os.path.isdir(candidate) and _is_project_root(candidate):
                return candidate
    except OSError:
        pass

    return None
