"""Connection Tester — probes external services to validate credentials.

Makes lightweight API calls to verify that user-provided credentials
are valid and the external service is reachable. Each test method
returns a TestResult with success status, response time, and
actionable error messages with suggestions.

All external calls use a 10-second timeout. Errors are categorized
into timeout, authentication failure, and network error — each with
a user-friendly suggestion for resolution.

Requirements: 6.1, 6.2, 6.3, 6.4, 6.5
Design: §Connection Tester
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────────────────

REQUEST_TIMEOUT_SECONDS = 10.0

NVIDIA_NIM_MODELS_URL = "https://integrate.api.nvidia.com/v1/models"
TELEGRAM_API_BASE = "https://api.telegram.org"
OLLAMA_LOCAL_URL = "http://localhost:11434/api/tags"


# ── Data Model ──────────────────────────────────────────────────────────────


@dataclass
class TestResult:
    """Result of a connection test against an external service."""

    success: bool
    response_time_ms: Optional[float] = None
    error: Optional[str] = None
    suggestion: Optional[str] = None


# ── Connection Tester ───────────────────────────────────────────────────────


class ConnectionTester:
    """Probes external services to validate credentials.

    Each test method makes a lightweight API call and returns a
    TestResult indicating whether the credentials are valid and
    the service is reachable.
    """

    async def test_nvidia_nim(self, api_key: str) -> TestResult:
        """Validate NVIDIA NIM API key by listing available models.

        Makes a GET request to the NVIDIA models endpoint with the
        provided API key as a Bearer token.
        """
        if not api_key:
            return TestResult(
                success=False,
                error="API key is empty",
                suggestion="Provide your NVIDIA NIM API key from build.nvidia.com",
            )

        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                response = await client.get(
                    NVIDIA_NIM_MODELS_URL,
                    headers={"Authorization": f"Bearer {api_key}"},
                )

            elapsed_ms = (time.perf_counter() - start) * 1000

            if response.status_code == 200:
                return TestResult(success=True, response_time_ms=round(elapsed_ms, 1))

            if response.status_code in (401, 403):
                return TestResult(
                    success=False,
                    response_time_ms=round(elapsed_ms, 1),
                    error="Authentication failed — verify your API key is active",
                    suggestion=(
                        "Check that your NVIDIA NIM API key has not expired. "
                        "Generate a new key at build.nvidia.com if needed."
                    ),
                )

            if response.status_code == 429:
                return TestResult(
                    success=False,
                    response_time_ms=round(elapsed_ms, 1),
                    error="Rate limited by NVIDIA API",
                    suggestion="Wait 60 seconds and retry the connection test.",
                )

            return TestResult(
                success=False,
                response_time_ms=round(elapsed_ms, 1),
                error=f"Unexpected response (HTTP {response.status_code})",
                suggestion="Try again in a few minutes. If the issue persists, check NVIDIA's status page.",
            )

        except httpx.TimeoutException:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return TestResult(
                success=False,
                response_time_ms=round(elapsed_ms, 1),
                error="Service unreachable — check your network",
                suggestion=(
                    "The request timed out after 10 seconds. "
                    "Check your internet connection or try again later."
                ),
            )
        except httpx.ConnectError:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return TestResult(
                success=False,
                response_time_ms=round(elapsed_ms, 1),
                error="Cannot connect to NVIDIA API",
                suggestion=(
                    "Check your internet connection and ensure "
                    "integrate.api.nvidia.com is not blocked by a firewall."
                ),
            )
        except httpx.HTTPError as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.warning("NVIDIA NIM connection test failed: %s", exc)
            return TestResult(
                success=False,
                response_time_ms=round(elapsed_ms, 1),
                error=f"Network error: {type(exc).__name__}",
                suggestion="Check your internet connection and try again.",
            )

    async def test_nubra(
        self, phone: str, mpin: str, totp_secret: str
    ) -> TestResult:
        """Validate Nubra.io credentials by checking format and structure.

        Since the Nubra.io login handshake requires a live TOTP code
        generated from the secret, this method validates credential
        format and structure rather than making a full login attempt.
        A successful format validation indicates the credentials are
        properly formed for the login flow.
        """
        start = time.perf_counter()

        # Validate phone number format (10 digits)
        if not phone or not re.match(r"^\d{10}$", phone):
            elapsed_ms = (time.perf_counter() - start) * 1000
            return TestResult(
                success=False,
                response_time_ms=round(elapsed_ms, 1),
                error="Invalid phone number format",
                suggestion="Phone number must be exactly 10 digits.",
            )

        # Validate MPIN format (4-6 digits)
        if not mpin or not re.match(r"^\d{4,6}$", mpin):
            elapsed_ms = (time.perf_counter() - start) * 1000
            return TestResult(
                success=False,
                response_time_ms=round(elapsed_ms, 1),
                error="Invalid MPIN format",
                suggestion="MPIN must be 4-6 digits.",
            )

        # Validate TOTP secret format (base32-like, 16+ chars)
        if not totp_secret or not re.match(r"^[A-Za-z0-9+/=]{16,}$", totp_secret):
            elapsed_ms = (time.perf_counter() - start) * 1000
            return TestResult(
                success=False,
                response_time_ms=round(elapsed_ms, 1),
                error="Invalid TOTP secret format",
                suggestion=(
                    "TOTP secret must be at least 16 characters (base32 encoded). "
                    "Run 'python scripts/nubra_setup_totp.py' to generate one."
                ),
            )

        elapsed_ms = (time.perf_counter() - start) * 1000
        return TestResult(
            success=True,
            response_time_ms=round(elapsed_ms, 1),
        )

    async def test_broker_shoonya(
        self, api_key: str, client_id: str
    ) -> TestResult:
        """Validate Shoonya broker credentials by checking format.

        Validates that the API key and client ID match expected formats.
        A full login requires additional credentials (password, TOTP)
        and session management, so this performs format validation
        to confirm credentials are properly structured.
        """
        start = time.perf_counter()

        # Validate API key (minimum 8 characters)
        if not api_key or len(api_key) < 8:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return TestResult(
                success=False,
                response_time_ms=round(elapsed_ms, 1),
                error="Invalid API key format",
                suggestion=(
                    "Shoonya API key must be at least 8 characters. "
                    "Get your key from the Shoonya developer portal."
                ),
            )

        # Validate client ID (uppercase alphanumeric, 4+ chars)
        if not client_id or not re.match(r"^[A-Z0-9]{4,}$", client_id):
            elapsed_ms = (time.perf_counter() - start) * 1000
            return TestResult(
                success=False,
                response_time_ms=round(elapsed_ms, 1),
                error="Invalid client ID format",
                suggestion=(
                    "Client ID must be uppercase letters and numbers, "
                    "at least 4 characters (e.g., 'FA12345')."
                ),
            )

        elapsed_ms = (time.perf_counter() - start) * 1000
        return TestResult(
            success=True,
            response_time_ms=round(elapsed_ms, 1),
        )

    async def test_telegram(self, bot_token: str) -> TestResult:
        """Validate Telegram bot token by calling the getMe endpoint.

        Makes a GET request to the Telegram Bot API to verify the
        token is valid and the bot is accessible.
        """
        if not bot_token:
            return TestResult(
                success=False,
                error="Bot token is empty",
                suggestion="Provide your Telegram bot token from @BotFather.",
            )

        start = time.perf_counter()
        url = f"{TELEGRAM_API_BASE}/bot{bot_token}/getMe"

        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                response = await client.get(url)

            elapsed_ms = (time.perf_counter() - start) * 1000

            if response.status_code == 200:
                data = response.json()
                if data.get("ok"):
                    return TestResult(
                        success=True, response_time_ms=round(elapsed_ms, 1)
                    )

            if response.status_code == 401:
                return TestResult(
                    success=False,
                    response_time_ms=round(elapsed_ms, 1),
                    error="Authentication failed — verify your bot token",
                    suggestion=(
                        "The bot token is invalid or has been revoked. "
                        "Create a new bot via @BotFather on Telegram."
                    ),
                )

            if response.status_code == 429:
                return TestResult(
                    success=False,
                    response_time_ms=round(elapsed_ms, 1),
                    error="Rate limited by Telegram API",
                    suggestion="Wait 60 seconds and retry the connection test.",
                )

            return TestResult(
                success=False,
                response_time_ms=round(elapsed_ms, 1),
                error=f"Unexpected response (HTTP {response.status_code})",
                suggestion="Verify your bot token format (should be like '123456:ABC-DEF...').",
            )

        except httpx.TimeoutException:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return TestResult(
                success=False,
                response_time_ms=round(elapsed_ms, 1),
                error="Service unreachable — check your network",
                suggestion=(
                    "The request timed out after 10 seconds. "
                    "Check your internet connection or try again later."
                ),
            )
        except httpx.ConnectError:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return TestResult(
                success=False,
                response_time_ms=round(elapsed_ms, 1),
                error="Cannot connect to Telegram API",
                suggestion=(
                    "Check your internet connection and ensure "
                    "api.telegram.org is not blocked by a firewall."
                ),
            )
        except httpx.HTTPError as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.warning("Telegram connection test failed: %s", exc)
            return TestResult(
                success=False,
                response_time_ms=round(elapsed_ms, 1),
                error=f"Network error: {type(exc).__name__}",
                suggestion="Check your internet connection and try again.",
            )

    async def test_ollama(self) -> TestResult:
        """Check if Ollama is running locally by querying the tags endpoint.

        Makes a GET request to the local Ollama API to verify it is
        running and responsive.
        """
        start = time.perf_counter()

        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                response = await client.get(OLLAMA_LOCAL_URL)

            elapsed_ms = (time.perf_counter() - start) * 1000

            if response.status_code == 200:
                return TestResult(success=True, response_time_ms=round(elapsed_ms, 1))

            return TestResult(
                success=False,
                response_time_ms=round(elapsed_ms, 1),
                error=f"Ollama returned unexpected status (HTTP {response.status_code})",
                suggestion="Ensure Ollama is running correctly. Try restarting with 'ollama serve'.",
            )

        except httpx.TimeoutException:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return TestResult(
                success=False,
                response_time_ms=round(elapsed_ms, 1),
                error="Service unreachable — check your network",
                suggestion=(
                    "Ollama did not respond within 10 seconds. "
                    "Ensure it is running with 'ollama serve'."
                ),
            )
        except httpx.ConnectError:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return TestResult(
                success=False,
                response_time_ms=round(elapsed_ms, 1),
                error="Ollama is not running on localhost:11434",
                suggestion=(
                    "Install Ollama from ollama.com/download and start it "
                    "with 'ollama serve'. Then pull a model with "
                    "'ollama pull llama3'."
                ),
            )
        except httpx.HTTPError as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.warning("Ollama connection test failed: %s", exc)
            return TestResult(
                success=False,
                response_time_ms=round(elapsed_ms, 1),
                error=f"Network error: {type(exc).__name__}",
                suggestion="Ensure Ollama is running with 'ollama serve' and try again.",
            )
