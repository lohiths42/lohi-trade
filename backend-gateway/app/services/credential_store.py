"""Credential Store — reads/writes API keys to .env files securely.

Handles the persistence layer for the Setup Wizard. Credentials are
stored in `.env` (trading) and `.env.research` (AI/research) files
at the repository root. Both files are gitignored and chmod 600.

Security guarantees:
- Never logs credential values (only key names + success/failure)
- Verifies .gitignore coverage before writing
- Sets file permissions to owner-read-write only (Unix)
- Uses atomic write (temp file + rename) to prevent corruption

Requirements: 5.1, 5.2, 5.3, 5.4, 5.6
Design: §Credential Store
"""

from __future__ import annotations

import logging
import os
import re
import stat
import tempfile
from pathlib import Path

from .service_registry import _GROUPS_BY_ID

logger = logging.getLogger(__name__)


class CredentialStore:
    """Reads and writes credentials to .env files."""

    def __init__(self, repo_root: str | Path):
        self.repo_root = Path(repo_root)
        self.env_path = self.repo_root / ".env"
        self.env_research_path = self.repo_root / ".env.research"

    # ── Public API ──────────────────────────────────────────────────────

    def write_credentials(self, group_id: str, credentials: dict[str, str]) -> None:
        """Write key=value pairs to the appropriate .env file.

        Validates that the group exists and all keys belong to it.
        Uses atomic write to prevent corruption on crash.
        """
        group = _GROUPS_BY_ID.get(group_id)
        if group is None:
            raise ValueError(f"Unknown credential group: {group_id}")

        # Validate keys belong to this group
        allowed_keys = set(group.credential_keys)
        for key in credentials:
            if key not in allowed_keys:
                raise ValueError(
                    f"Key '{key}' does not belong to group '{group_id}'. "
                    f"Allowed: {sorted(allowed_keys)}"
                )

        # Determine target file
        target = self._get_env_path(group.env_file)

        # Ensure gitignore coverage
        self.ensure_gitignore()

        # Read existing content, update/add keys
        existing = self._parse_env_file(target)
        for key, value in credentials.items():
            existing[key] = value

        # Write atomically
        self._write_env_file(target, existing)

        # Set permissions
        self.set_file_permissions()

        logger.info(
            "Credentials written for group '%s' (%d keys)",
            group_id,
            len(credentials),
        )

    def read_credentials(self, group_id: str) -> dict[str, str]:
        """Read current values for a group's keys.

        Returns empty strings for unset keys. Never logs values.
        """
        group = _GROUPS_BY_ID.get(group_id)
        if group is None:
            return {}

        target = self._get_env_path(group.env_file)
        existing = self._parse_env_file(target)

        result = {}
        for key in group.credential_keys:
            value = existing.get(key, "")
            # Return masked indicator (non-empty vs empty) — never the actual value
            result[key] = "configured" if value else ""
        return result

    def read_raw_credentials(self, group_id: str) -> dict[str, str]:
        """Read actual credential values (for connection testing only).

        This method returns real values. Only call from the connection
        tester, never from API responses to the frontend.
        """
        group = _GROUPS_BY_ID.get(group_id)
        if group is None:
            return {}

        target = self._get_env_path(group.env_file)
        existing = self._parse_env_file(target)

        return {key: existing.get(key, "") for key in group.credential_keys}

    def clear_credentials(self, group_id: str) -> None:
        """Remove/blank credential keys for a group."""
        group = _GROUPS_BY_ID.get(group_id)
        if group is None:
            return

        target = self._get_env_path(group.env_file)
        existing = self._parse_env_file(target)

        for key in group.credential_keys:
            existing[key] = ""

        self._write_env_file(target, existing)
        logger.info("Credentials cleared for group '%s'", group_id)

    def ensure_gitignore(self) -> bool:
        """Verify .env files are in .gitignore; add if missing.

        Returns True if .gitignore was modified.
        """
        gitignore_path = self.repo_root / ".gitignore"
        entries_needed = [".env", ".env.research"]

        if not gitignore_path.exists():
            gitignore_path.write_text("\n".join(entries_needed) + "\n", encoding="utf-8")
            logger.warning("Created .gitignore with .env entries")
            return True

        content = gitignore_path.read_text(encoding="utf-8")
        lines = content.splitlines()
        modified = False

        for entry in entries_needed:
            if not any(line.strip() == entry for line in lines):
                lines.append(entry)
                modified = True
                logger.warning("Added '%s' to .gitignore", entry)

        if modified:
            gitignore_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        return modified

    def set_file_permissions(self) -> None:
        """chmod 600 on .env files (Unix only, no-op on Windows)."""
        if os.name != "posix":
            return

        for path in (self.env_path, self.env_research_path):
            if path.exists():
                try:
                    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
                except OSError as exc:
                    logger.warning("Failed to set permissions on %s: %s", path, exc)

    def validate_credentials(self, group_id: str, credentials: dict[str, str]) -> dict[str, str]:
        """Validate credential format against regex patterns.

        Returns a dict of field_name → error_message for invalid fields.
        Empty dict means all valid.
        """
        group = _GROUPS_BY_ID.get(group_id)
        if group is None:
            return {"_group": f"Unknown group: {group_id}"}

        errors: dict[str, str] = {}
        for key in group.credential_keys:
            value = credentials.get(key, "")
            pattern = group.validation_patterns.get(key)

            if not value:
                errors[key] = "This field is required"
                continue

            if pattern and not re.match(pattern, value):
                errors[key] = f"Invalid format (expected pattern: {pattern})"

        return errors

    # ── Internal ────────────────────────────────────────────────────────

    def _get_env_path(self, env_file: str) -> Path:
        """Resolve the .env file path."""
        if env_file == ".env.research":
            return self.env_research_path
        return self.env_path

    def _parse_env_file(self, path: Path) -> dict[str, str]:
        """Parse a .env file into a key-value dict.

        Preserves comments and blank lines in the internal representation
        by only extracting KEY=VALUE lines. Non-KV lines are ignored
        during parse but preserved during write via the full-file approach.
        """
        if not path.exists():
            return {}

        result: dict[str, str] = {}
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if "=" in stripped:
                    key, _, value = stripped.partition("=")
                    key = key.strip()
                    value = value.strip()
                    # Remove surrounding quotes if present
                    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                        value = value[1:-1]
                    result[key] = value
        except OSError as exc:
            logger.warning("Failed to read %s: %s", path, exc)

        return result

    def _write_env_file(self, path: Path, data: dict[str, str]) -> None:
        """Write key=value pairs to a .env file atomically.

        Preserves existing comments and structure where possible.
        Uses temp file + rename for atomic write.
        """
        # Read existing file to preserve comments/structure
        existing_lines: list[str] = []
        if path.exists():
            try:
                existing_lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                pass

        # Track which keys we've written
        written_keys: set[str] = set()
        output_lines: list[str] = []

        for line in existing_lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key = stripped.partition("=")[0].strip()
                if key in data:
                    output_lines.append(f"{key}={data[key]}")
                    written_keys.add(key)
                else:
                    output_lines.append(line)
            else:
                output_lines.append(line)

        # Append any new keys not already in the file
        for key, value in data.items():
            if key not in written_keys:
                output_lines.append(f"{key}={value}")

        # Atomic write: write to temp, then rename
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=".env_tmp_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write("\n".join(output_lines) + "\n")
            os.replace(tmp_path, str(path))
        except Exception:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
