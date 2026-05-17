"""Property-based tests for Port Conflict Detection.

Verifies that the port checking logic correctly detects all port conflicts
and returns port number + process information for any combination of
occupied ports from the required set {5432, 6379, 8000, 3000}.

# Feature: easy-setup-wizard, Property 8: Port conflict detection

**Validates: Requirements 9.5**

Properties tested:
  1. For any subset of ports from {5432, 6379, 8000, 3000} that are occupied,
     check_ports() SHALL detect all conflicts and return port number + process info.
"""

import sys
from pathlib import Path
from typing import NamedTuple
from unittest.mock import patch

from hypothesis import given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Import shim for backend-gateway (hyphenated directory name)
# ---------------------------------------------------------------------------

_backend_gateway_dir = str(
    Path(__file__).resolve().parents[1] / "backend-gateway",
)
if _backend_gateway_dir not in sys.path:
    sys.path.insert(0, _backend_gateway_dir)

# ---------------------------------------------------------------------------
# Python implementation of port checking logic (mirrors setup.sh check_ports)
# ---------------------------------------------------------------------------

REQUIRED_PORTS = {5432, 6379, 8000, 3000}

PORT_DESCRIPTIONS = {
    5432: "PostgreSQL",
    6379: "Redis",
    8000: "Backend gateway",
    3000: "Frontend dev server",
}


class PortConflict(NamedTuple):
    """Represents a detected port conflict."""

    port: int
    pid: int
    process_name: str
    description: str


def check_ports(occupied_ports: dict[int, tuple[int, str]]) -> list[PortConflict]:
    """Check required ports for conflicts.

    This is a Python implementation mirroring the setup.sh check_ports() logic.
    It checks each port in REQUIRED_PORTS and returns conflict information
    for any port that is occupied.

    Args:
        occupied_ports: A mapping of port number -> (pid, process_name) for
                        ports that are currently in use.

    Returns:
        A list of PortConflict entries for each required port that is occupied.

    """
    conflicts: list[PortConflict] = []

    for port in sorted(REQUIRED_PORTS):
        if port in occupied_ports:
            pid, process_name = occupied_ports[port]
            conflicts.append(
                PortConflict(
                    port=port,
                    pid=pid,
                    process_name=process_name,
                    description=PORT_DESCRIPTIONS.get(port, "Unknown service"),
                ),
            )

    return conflicts


def check_ports_with_lsof() -> list[PortConflict]:
    """Check ports using lsof/system calls (production version).

    This function uses subprocess to call lsof (or ss/netstat as fallback)
    to detect actual port occupation, mirroring setup.sh behavior.
    """
    import subprocess

    conflicts: list[PortConflict] = []

    for port in sorted(REQUIRED_PORTS):
        pid = None
        process_name = "unknown"

        try:
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                pid_str = result.stdout.strip().split("\n")[0]
                pid = int(pid_str)
                # Get process name
                ps_result = subprocess.run(
                    ["ps", "-p", str(pid), "-o", "comm="],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if ps_result.returncode == 0 and ps_result.stdout.strip():
                    process_name = ps_result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
            # lsof not available, try ss
            try:
                result = subprocess.run(
                    ["ss", "-tlnp", f"sport = :{port}"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    import re

                    match = re.search(r"pid=(\d+)", result.stdout)
                    if match:
                        pid = int(match.group(1))
                        ps_result = subprocess.run(
                            ["ps", "-p", str(pid), "-o", "comm="],
                            capture_output=True,
                            text=True,
                            timeout=5,
                        )
                        if ps_result.returncode == 0 and ps_result.stdout.strip():
                            process_name = ps_result.stdout.strip()
            except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
                pass

        if pid is not None:
            conflicts.append(
                PortConflict(
                    port=port,
                    pid=pid,
                    process_name=process_name,
                    description=PORT_DESCRIPTIONS.get(port, "Unknown service"),
                ),
            )

    return conflicts


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Strategy: generate a random subset of ports from REQUIRED_PORTS to "occupy"
occupied_ports_strategy = st.frozensets(
    st.sampled_from(sorted(REQUIRED_PORTS)),
)

# Strategy: generate random PIDs (realistic range)
pid_strategy = st.integers(min_value=1, max_value=65535)

# Strategy: generate random process names
process_name_strategy = st.sampled_from(
    ["postgres", "redis-server", "python3", "node", "uvicorn", "vite", "nginx", "httpd"],
)

# Combined strategy: generate occupied port scenarios with process info
port_occupation_strategy = st.frozensets(
    st.sampled_from(sorted(REQUIRED_PORTS)),
).flatmap(
    lambda ports: st.fixed_dictionaries(
        {port: st.tuples(pid_strategy, process_name_strategy) for port in ports},
    ),
)


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------


class TestPortConflictDetection:
    """Property 8: Port conflict detection."""

    @given(occupation=port_occupation_strategy)
    @settings(max_examples=200)
    def test_all_occupied_ports_detected(
        self,
        occupation: dict[int, tuple[int, str]],
    ) -> None:
        """For any port in {5432, 6379, 8000, 3000} that is occupied,
        check_ports() SHALL detect the conflict and return the port number
        and conflicting process information.

        **Validates: Requirements 9.5**
        """
        conflicts = check_ports(occupation)

        # Every occupied port must be detected
        detected_ports = {c.port for c in conflicts}
        occupied_port_set = set(occupation.keys())

        assert detected_ports == occupied_port_set, (
            f"Port detection mismatch: "
            f"occupied={sorted(occupied_port_set)}, "
            f"detected={sorted(detected_ports)}"
        )

    @given(occupation=port_occupation_strategy)
    @settings(max_examples=200)
    def test_conflict_contains_port_and_process_info(
        self,
        occupation: dict[int, tuple[int, str]],
    ) -> None:
        """For each detected conflict, the result SHALL contain the port number
        and the conflicting process information (PID and process name).

        **Validates: Requirements 9.5**
        """
        conflicts = check_ports(occupation)

        for conflict in conflicts:
            # Port must be in the required set
            assert (
                conflict.port in REQUIRED_PORTS
            ), f"Detected port {conflict.port} is not in required set {REQUIRED_PORTS}"

            # PID must match what was provided
            expected_pid, expected_name = occupation[conflict.port]
            assert (
                conflict.pid == expected_pid
            ), f"Port {conflict.port}: expected PID {expected_pid}, got {conflict.pid}"
            assert conflict.process_name == expected_name, (
                f"Port {conflict.port}: expected process '{expected_name}', "
                f"got '{conflict.process_name}'"
            )

            # Description must be non-empty
            assert conflict.description, f"Port {conflict.port}: description should not be empty"

    @given(occupation=port_occupation_strategy)
    @settings(max_examples=200)
    def test_no_false_positives(
        self,
        occupation: dict[int, tuple[int, str]],
    ) -> None:
        """check_ports() SHALL NOT report conflicts for ports that are not
        occupied. Only actually occupied ports should appear in the result.

        **Validates: Requirements 9.5**
        """
        conflicts = check_ports(occupation)

        free_ports = REQUIRED_PORTS - set(occupation.keys())
        detected_ports = {c.port for c in conflicts}

        # No free port should be reported as a conflict
        false_positives = detected_ports & free_ports
        assert not false_positives, (
            f"False positives detected: ports {sorted(false_positives)} "
            f"are free but reported as conflicts"
        )

    @given(occupation=port_occupation_strategy)
    @settings(max_examples=200)
    def test_conflicts_ordered_by_port(
        self,
        occupation: dict[int, tuple[int, str]],
    ) -> None:
        """check_ports() SHALL return conflicts in port-number order,
        matching the setup.sh iteration order.

        **Validates: Requirements 9.5**
        """
        conflicts = check_ports(occupation)

        port_list = [c.port for c in conflicts]
        assert port_list == sorted(port_list), f"Conflicts not in port order: {port_list}"

    @given(data=st.data())
    @settings(max_examples=100)
    def test_lsof_based_detection_with_mock(self, data: st.DataObject) -> None:
        """When using the lsof-based detection (production path), occupied
        ports SHALL be detected via subprocess calls and return correct
        port + process info.

        **Validates: Requirements 9.5**
        """
        # Generate a random subset of ports to occupy
        occupied_set = data.draw(
            st.frozensets(st.sampled_from(sorted(REQUIRED_PORTS))),
        )

        # Use unique PIDs per port to avoid ambiguity in the mock
        occupied_list = sorted(occupied_set)
        pids = {port: 1000 + i for i, port in enumerate(occupied_list)}
        names = {port: data.draw(process_name_strategy) for port in occupied_list}

        # Build reverse lookup: pid -> process_name
        pid_to_name: dict[int, str] = {pids[port]: names[port] for port in occupied_list}

        import subprocess

        def mock_run(cmd, **kwargs):
            """Mock subprocess.run to simulate lsof and ps behavior."""
            result = subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="")

            if cmd[0] == "lsof" and len(cmd) >= 3:
                # Parse port from -ti :PORT
                port_arg = cmd[2]  # e.g., ":5432"
                port = int(port_arg.lstrip(":"))
                if port in occupied_set:
                    result.returncode = 0
                    result.stdout = str(pids[port]) + "\n"

            elif cmd[0] == "ps" and "-p" in cmd:
                pid_idx = cmd.index("-p") + 1
                pid = int(cmd[pid_idx])
                if pid in pid_to_name:
                    result.returncode = 0
                    result.stdout = pid_to_name[pid] + "\n"

            return result

        with patch("subprocess.run", side_effect=mock_run):
            conflicts = check_ports_with_lsof()

        detected_ports = {c.port for c in conflicts}
        assert detected_ports == occupied_set, (
            f"lsof-based detection mismatch: "
            f"occupied={sorted(occupied_set)}, "
            f"detected={sorted(detected_ports)}"
        )

        # Verify process info for each conflict
        for conflict in conflicts:
            assert conflict.pid == pids[conflict.port], (
                f"Port {conflict.port}: expected PID {pids[conflict.port]}, " f"got {conflict.pid}"
            )
            assert conflict.process_name == names[conflict.port], (
                f"Port {conflict.port}: expected process '{names[conflict.port]}', "
                f"got '{conflict.process_name}'"
            )
