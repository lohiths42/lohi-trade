#!/usr/bin/env python3
"""
Comprehensive test runner for LOHI-TRADE.
Runs all unit tests, property tests, and performance tests.
Generates coverage report.

Requirements: 26.1-26.7, 24.1, 24.2, 24.5
"""
import subprocess
import sys
import time


def run_tests():
    """Run the full test suite with coverage and return the exit code."""
    print("=" * 70)
    print("  LOHI-TRADE — Comprehensive Test Suite")
    print("=" * 70)

    start = time.time()

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/",
            "-v",
            "--tb=short",
            "-q",
            "--cov=src/execution",
            "--cov=src/soldier",
            "--cov=src/ingestion",
            "--cov=src/state",
            "--cov-report=term-missing",
        ],
        capture_output=False,
    )

    elapsed = time.time() - start

    print()
    print("=" * 70)
    if result.returncode == 0:
        print(f"  ALL TESTS PASSED  ({elapsed:.1f}s)")
    else:
        print(f"  SOME TESTS FAILED  (exit code {result.returncode}, {elapsed:.1f}s)")
    print("=" * 70)

    return result.returncode


if __name__ == "__main__":
    sys.exit(run_tests())
