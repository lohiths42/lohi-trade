"""Console output utilities — colored, structured terminal output."""

from __future__ import annotations

import sys

# ── ANSI Colors ──────────────────────────────────────────────────────────────


def _supports_color() -> bool:
    """Check if the terminal supports color output."""
    if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
        return False
    return True


_COLOR = _supports_color()


def _c(code: str, text: str) -> str:
    if not _COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def green(text: str) -> str:
    return _c("0;32", text)


def red(text: str) -> str:
    return _c("0;31", text)


def yellow(text: str) -> str:
    return _c("1;33", text)


def blue(text: str) -> str:
    return _c("0;34", text)


def bold(text: str) -> str:
    return _c("1", text)


def dim(text: str) -> str:
    return _c("2", text)


# ── Structured Output ────────────────────────────────────────────────────────


def success(msg: str) -> None:
    """Print a success message with green checkmark."""
    print(f"  {green('✓')} {msg}")


def error(msg: str) -> None:
    """Print an error message with red X."""
    print(f"  {red('✗')} {msg}")


def warn(msg: str) -> None:
    """Print a warning message with yellow triangle."""
    print(f"  {yellow('⚠')} {msg}")


def info(msg: str) -> None:
    """Print an info message (indented)."""
    print(f"    {msg}")


def phase(msg: str) -> None:
    """Print a phase header."""
    print(f"\n  {blue(bold('▶'))} {bold(msg)}")


def header(title: str) -> None:
    """Print a boxed header."""
    width = len(title) + 4
    border = "═" * width
    print()
    print(f"  {bold('╔' + border + '╗')}")
    print(f"  {bold('║')}  {title}  {bold('║')}")
    print(f"  {bold('╚' + border + '╝')}")
    print()


def done(msg: str) -> None:
    """Print a completion message in green."""
    print()
    print(f"  {green(bold(msg))}")
    print()


def table(rows: list[tuple[str, str, str]], headers: tuple[str, str, str] | None = None) -> None:
    """Print a simple 3-column table."""
    if headers:
        rows = [headers] + rows

    # Calculate column widths
    col_widths = [0, 0, 0]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell))

    # Print rows
    for i, row in enumerate(rows):
        line = "  "
        for j, cell in enumerate(row):
            line += cell.ljust(col_widths[j] + 3)
        print(line)
        if i == 0 and headers:
            print("  " + "─" * (sum(col_widths) + 9))
