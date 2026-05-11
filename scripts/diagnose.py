#!/usr/bin/env python3
"""Lohi-TRADE Diagnostic Tool — reads logs, checks health, suggests fixes.

Usage:
    python scripts/diagnose.py              # full diagnostic
    python scripts/diagnose.py --component research   # research only
    python scripts/diagnose.py --last 100   # last 100 log lines only
    python scripts/diagnose.py --fix        # attempt auto-fixes where safe

This tool is designed to be run by the user (not by the LLM pipeline)
when something isn't working. It reads structured logs, checks service
health, and prints actionable suggestions in plain English.

No destructive operations. Read-only except when --fix is passed,
and even then only safe operations (restart workers, clear stale
caches, re-create missing directories).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Setup ───────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs"
DATA_DIR = ROOT / "data"
BACKEND_DIR = ROOT / "backend-gateway"

# ANSI colors for terminal output
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def ok(msg: str) -> None:
    print(f"  {GREEN}✓{RESET} {msg}")


def warn(msg: str) -> None:
    print(f"  {YELLOW}!{RESET} {msg}")


def err(msg: str) -> None:
    print(f"  {RED}✗{RESET} {msg}")


def info(msg: str) -> None:
    print(f"  {CYAN}→{RESET} {msg}")


def header(title: str) -> None:
    print(f"\n{BOLD}{'═' * 60}{RESET}")
    print(f"{BOLD}  {title}{RESET}")
    print(f"{BOLD}{'═' * 60}{RESET}\n")


# ── Checks ──────────────────────────────────────────────────────────────────


def check_services() -> list[str]:
    """Check if gateway, frontend, ticker, and research workers are running."""
    issues = []
    header("Service Health")

    services = {
        "Gateway (port 8000)": ("lsof", "-ti:8000"),
        "Frontend (port 3000)": ("lsof", "-ti:3000"),
        "Nubra Ticker": ("pgrep", "-f", "nubra_ticker.py"),
        "Redis (port 6379)": ("lsof", "-ti:6379"),
        "Postgres (port 5432)": ("lsof", "-ti:5432"),
    }

    for name, cmd in services.items():
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and result.stdout.strip():
                pids = result.stdout.strip().split("\n")
                ok(f"{name}: running (PID {pids[0]})")
            else:
                err(f"{name}: NOT running")
                issues.append(f"{name} is not running")
        except Exception:
            err(f"{name}: check failed")
            issues.append(f"Could not check {name}")

    # Research workers
    for worker in ("orchestrator", "indexer", "snapshotter"):
        try:
            result = subprocess.run(
                ["pgrep", "-f", f"research.workers.{worker}"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                ok(f"Research {worker}: running")
            else:
                warn(f"Research {worker}: not running (expected if research not started)")
        except Exception:
            pass

    return issues


def check_data_integrity() -> list[str]:
    """Check data directories, backups, and DB health."""
    issues = []
    header("Data Integrity")

    # Required directories
    dirs = [
        "data/research/chroma",
        "data/research/uploads",
        "data/research/snapshots",
        "data/backups",
        "logs",
    ]
    for d in dirs:
        p = ROOT / d
        if p.exists():
            ok(f"{d}/ exists")
        else:
            warn(f"{d}/ missing — will be created on next start")

    # Backup freshness
    backup_dir = ROOT / "data" / "backups"
    if backup_dir.exists():
        backups = sorted(backup_dir.glob("*.db"), key=os.path.getmtime, reverse=True)
        if backups:
            latest = backups[0]
            import time
            age_hours = (time.time() - os.path.getmtime(latest)) / 3600
            if age_hours < 48:
                ok(f"Latest backup: {latest.name} ({age_hours:.1f}h ago)")
            else:
                warn(f"Latest backup is {age_hours:.1f}h old: {latest.name}")
                issues.append("Backup is stale (>48h old)")
            ok(f"Total backups: {len(backups)}")
        else:
            warn("No backups found in data/backups/")
            issues.append("No database backups exist")
    else:
        warn("data/backups/ directory does not exist")
        issues.append("Backup directory missing")

    # SQLite DB
    sqlite_path = ROOT / "data" / "lohi_trade.db"
    if sqlite_path.exists():
        size_mb = sqlite_path.stat().st_size / (1024 * 1024)
        ok(f"SQLite DB: {size_mb:.1f} MB")
    else:
        info("SQLite DB not found (may be using Postgres only)")

    # Chroma DB
    chroma_path = ROOT / "data" / "research" / "chroma"
    if chroma_path.exists():
        total = sum(f.stat().st_size for f in chroma_path.rglob("*") if f.is_file())
        ok(f"Chroma vector DB: {total / (1024*1024):.1f} MB")
    else:
        info("Chroma DB not initialized yet (will be created on first research run)")

    return issues


def check_config() -> list[str]:
    """Check configuration files and environment."""
    issues = []
    header("Configuration")

    # .env files
    env_files = [
        ".env.research",
        "backend-gateway/.env",
        "config/settings.yaml",
    ]
    for ef in env_files:
        p = ROOT / ef
        if p.exists():
            ok(f"{ef} exists")
        else:
            err(f"{ef} MISSING")
            issues.append(f"{ef} not found")

    # Check if LLM is configured
    env_research = ROOT / ".env.research"
    if env_research.exists():
        content = env_research.read_text()
        if "NVIDIA_NIM_API_KEY=" in content:
            key_line = [l for l in content.splitlines() if "NVIDIA_NIM_API_KEY=" in l]
            if key_line:
                val = key_line[0].split("=", 1)[1].strip()
                if val and "placeholder" not in val.lower() and "demo" not in val.lower():
                    ok("NVIDIA NIM API key: configured")
                else:
                    warn("NVIDIA NIM API key: placeholder/demo value")
                    issues.append("No real LLM API key configured — research runs will fail")
        if "LOHI_RESEARCH_OFFLINE=true" in content.lower():
            info("Offline mode: enabled (requires Ollama)")
            # Check Ollama
            try:
                result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    ok("Ollama: available")
                else:
                    err("Ollama: not responding")
                    issues.append("Offline mode enabled but Ollama not available")
            except FileNotFoundError:
                err("Ollama: not installed")
                issues.append("Offline mode enabled but Ollama not installed")

    return issues


def check_recent_errors(last_n: int = 50) -> list[str]:
    """Scan recent log files for errors and warnings."""
    issues = []
    header("Recent Errors")

    log_files = sorted(LOG_DIR.glob("*.log"), key=os.path.getmtime, reverse=True)
    if not log_files:
        info("No log files found in logs/")
        return issues

    error_count = 0
    warning_count = 0
    recent_errors: list[str] = []

    for lf in log_files[:5]:  # Check last 5 log files
        try:
            lines = lf.read_text(errors="replace").splitlines()[-last_n:]
            for line in lines:
                if "ERROR" in line or "CRITICAL" in line:
                    error_count += 1
                    if len(recent_errors) < 10:
                        recent_errors.append(f"  [{lf.name}] {line[:120]}")
                elif "WARNING" in line:
                    warning_count += 1
        except Exception:
            pass

    if error_count == 0:
        ok("No recent errors in logs")
    else:
        err(f"{error_count} errors found in recent logs")
        for e in recent_errors[:5]:
            print(f"    {RED}{e}{RESET}")
        if error_count > 5:
            info(f"... and {error_count - 5} more. Run with --last 200 for full view.")
        issues.append(f"{error_count} errors in recent logs")

    if warning_count > 0:
        warn(f"{warning_count} warnings in recent logs")

    return issues


def suggest_fixes(issues: list[str]) -> None:
    """Print actionable fix suggestions based on discovered issues."""
    if not issues:
        return

    header("Suggested Fixes")

    fix_map = {
        "not running": (
            "Start the missing service:\n"
            "  Gateway:  cd backend-gateway && uvicorn app.main:socket_app --port 8000 &\n"
            "  Frontend: cd 'Lohi-TRADE Web App Design' && npm run dev -- --port 3000 &\n"
            "  Ticker:   cd backend-gateway && python scripts/nubra_ticker.py &\n"
            "  Redis:    docker compose up -d redis\n"
            "  Postgres: docker compose up -d postgres"
        ),
        "No real LLM API key": (
            "To enable research briefs, you need an LLM. Two options:\n"
            "  Option A (cloud, fast): Sign up at https://build.nvidia.com,\n"
            "           get a free API key, add to .env.research:\n"
            "           NVIDIA_NIM_API_KEY=nvapi-...\n"
            "  Option B (local, private): Install Ollama from https://ollama.com/download,\n"
            "           run: ollama pull gemma3:12b\n"
            "           set in .env.research: LOHI_RESEARCH_OFFLINE=true"
        ),
        "Ollama not installed": (
            "Install Ollama:\n"
            "  1. Download from https://ollama.com/download/mac\n"
            "  2. Open Ollama.app\n"
            "  3. Run: ollama pull gemma3:12b (or llama3.1:8b)"
        ),
        "Backup": (
            "Create a fresh backup:\n"
            "  python -c \"from src.state.database_backup import DatabaseBackupManager; "
            "m = DatabaseBackupManager('data/lohi_trade.db'); m.create_backup()\""
        ),
        "errors in recent logs": (
            "Review the full error context:\n"
            "  tail -100 logs/research-*.log | grep -A2 ERROR\n"
            "  Or run: python scripts/diagnose.py --last 200"
        ),
    }

    printed = set()
    for issue in issues:
        for key, fix in fix_map.items():
            if key.lower() in issue.lower() and key not in printed:
                info(f"Fix for: {issue}")
                print(f"    {fix}\n")
                printed.add(key)
                break
        else:
            info(f"Issue: {issue} — check logs for details")


# ── Main ────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description="Lohi-TRADE Diagnostic Tool")
    parser.add_argument("--component", help="Check specific component only")
    parser.add_argument("--last", type=int, default=50, help="Number of log lines to scan")
    parser.add_argument("--fix", action="store_true", help="Attempt safe auto-fixes")
    args = parser.parse_args()

    os.chdir(ROOT)

    print(f"\n{BOLD}{CYAN}╔══════════════════════════════════════════╗{RESET}")
    print(f"{BOLD}{CYAN}║     🔍 Lohi-TRADE Diagnostic Report      ║{RESET}")
    print(f"{BOLD}{CYAN}╚══════════════════════════════════════════╝{RESET}")
    print(f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Root: {ROOT}")

    all_issues: list[str] = []

    all_issues.extend(check_services())
    all_issues.extend(check_data_integrity())
    all_issues.extend(check_config())
    all_issues.extend(check_recent_errors(args.last))

    # Summary
    header("Summary")
    if not all_issues:
        ok("All checks passed — system looks healthy!")
    else:
        err(f"{len(all_issues)} issue(s) found:")
        for i, issue in enumerate(all_issues, 1):
            print(f"    {i}. {issue}")

    suggest_fixes(all_issues)

    # Auto-fix if requested
    if args.fix and all_issues:
        header("Auto-Fix Attempts")
        # Only safe operations: create missing dirs
        for d in ("data/research/chroma", "data/research/uploads",
                  "data/research/snapshots", "data/backups", "logs"):
            p = ROOT / d
            if not p.exists():
                p.mkdir(parents=True, exist_ok=True)
                ok(f"Created {d}/")

    return 0 if not all_issues else 1


if __name__ == "__main__":
    sys.exit(main())
