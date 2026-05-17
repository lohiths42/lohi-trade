"""LOHI-TRADE CLI entry point.

Usage:
    lohi setup          Full bootstrap (deps → infra → backend → frontend → browser)
    lohi setup --skip-frontend   Backend-only setup
    lohi doctor         Check system dependencies and report issues
    lohi start          Start all services (assumes setup already done)
    lohi stop           Stop all running services
    lohi status         Show service health and configuration status
"""

from __future__ import annotations

import argparse
import sys

from src.cli import __version__


def main() -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="lohi",
        description="LOHI-TRADE — AI-powered algorithmic trading for Indian markets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  lohi setup              Full bootstrap (first time)\n"
            "  lohi doctor             Check system dependencies\n"
            "  lohi start              Start all services\n"
            "  lohi stop               Stop all services\n"
            "  lohi status             Show service health\n"
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"lohi-trade {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ── lohi setup ───────────────────────────────────────────────────────────
    setup_parser = subparsers.add_parser(
        "setup",
        help="Bootstrap the entire LOHI-TRADE stack",
        description="Checks dependencies, installs packages, starts infrastructure, and opens the setup wizard.",
    )
    setup_parser.add_argument(
        "--skip-frontend",
        action="store_true",
        help="Skip frontend installation and dev server",
    )
    setup_parser.add_argument(
        "--skip-docker",
        action="store_true",
        help="Skip Docker infrastructure (use existing PostgreSQL/Redis)",
    )
    setup_parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't open the browser after setup",
    )
    setup_parser.add_argument(
        "--offline",
        action="store_true",
        help="Run setup without network calls (skips pip install and npm install)",
    )
    setup_parser.add_argument(
        "--backend-port",
        type=int,
        default=8000,
        help="Port for the backend gateway (default: 8000)",
    )
    setup_parser.add_argument(
        "--frontend-port",
        type=int,
        default=3000,
        help="Port for the frontend dev server (default: 3000)",
    )

    # ── lohi doctor ──────────────────────────────────────────────────────────
    subparsers.add_parser(
        "doctor",
        help="Check system dependencies and report issues",
        description="Verifies Docker, Node.js, Python, and port availability.",
    )

    # ── lohi start ───────────────────────────────────────────────────────────
    start_parser = subparsers.add_parser(
        "start",
        help="Start all LOHI-TRADE services",
        description="Starts Docker infrastructure, backend gateway, and frontend dev server.",
    )
    start_parser.add_argument(
        "--backend-only",
        action="store_true",
        help="Only start the backend gateway",
    )

    # ── lohi stop ────────────────────────────────────────────────────────────
    subparsers.add_parser(
        "stop",
        help="Stop all running LOHI-TRADE services",
        description="Stops Docker containers and kills backend/frontend processes.",
    )

    # ── lohi status ──────────────────────────────────────────────────────────
    subparsers.add_parser(
        "status",
        help="Show service health and configuration status",
        description="Queries the backend health endpoint and shows service configuration.",
    )

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 0

    # Dispatch to command handlers
    if args.command == "setup":
        from src.cli.commands.setup import run_setup

        return run_setup(args)
    if args.command == "doctor":
        from src.cli.commands.doctor import run_doctor

        return run_doctor()
    if args.command == "start":
        from src.cli.commands.start import run_start

        return run_start(args)
    if args.command == "stop":
        from src.cli.commands.stop import run_stop

        return run_stop()
    if args.command == "status":
        from src.cli.commands.status import run_status

        return run_status()
    parser.print_help()
    return 1


def cli() -> None:
    """Entry point for the console_scripts."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
