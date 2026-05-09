"""AI Tax Profile Generator — uses LLM to generate/refresh tax rules.

Generates country-specific tax profiles using an LLM API call with
Pydantic-validated output. The generated profile MUST be verified by
the user before being used for calculations.

Flow:
1. User selects country in setup wizard
2. System loads pre-built profile (if available)
3. User can optionally click "Refresh Tax Rules via AI"
4. LLM generates updated TaxProfile as structured JSON
5. Pydantic validates the output
6. User reviews diff and confirms
7. Confirmed profile is persisted to config/market.yaml
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from pydantic import ValidationError

from .market_profile import Country, TaxProfile, TaxRule

logger = logging.getLogger(__name__)


# ── System Prompt ───────────────────────────────────────────────────────────

TAX_PROFILE_SYSTEM_PROMPT = """You are a financial tax expert specializing in stock market taxation across global markets.

Given a country code and country name, return the CURRENT stock market transaction taxes and capital gains rules as a JSON object matching this exact schema:

{schema}

RULES:
1. Include ALL transaction-level taxes that apply to stock trades in that country.
   Examples: Securities Transaction Tax, stamp duty, exchange fees, regulatory fees,
   clearing fees, GST/VAT on brokerage, etc.
2. Capital gains rates should reflect the TOP tax bracket (worst case for the user).
3. For countries with no capital gains tax (e.g., Singapore, Hong Kong), set rates to 0.
4. The short_term_threshold_days is the number of days after which gains qualify as long-term.
   Set to 0 if the country doesn't distinguish by holding period.
5. wash_sale_rule should be True if the country has rules preventing loss harvesting
   (e.g., US 30-day wash sale, UK bed-and-breakfasting, Canada superficial loss).
6. Set last_updated to today's date in ISO format.
7. Set source to "ai_generated".
8. Set verified_by_user to false.
9. Include a brief disclaimer noting this is an estimate.

Return ONLY valid JSON. No markdown, no explanations, no code blocks."""


# ── Generator Class ─────────────────────────────────────────────────────────


class TaxProfileGenerator:
    """Generates tax profiles using LLM API calls with Pydantic validation.

    Supports any LLM provider that implements the chat interface
    (NVIDIA NIM, OpenAI, Anthropic, Ollama, etc.).
    """

    def __init__(self, llm_provider=None):
        """Initialize with an optional LLM provider.

        Args:
            llm_provider: Any object with an async `chat(system, user)` method
                         that returns a string response. If None, generation
                         will fail gracefully with a helpful message.
        """
        self._llm = llm_provider

    async def generate(self, country: Country, country_name: str) -> TaxProfile:
        """Generate a tax profile for the given country using AI.

        Args:
            country: Country enum value
            country_name: Full country name for the prompt

        Returns:
            Validated TaxProfile

        Raises:
            TaxGenerationError: If LLM is unavailable or output is invalid
        """
        if self._llm is None:
            raise TaxGenerationError(
                "No LLM provider configured. Please configure NVIDIA NIM or Ollama "
                "in the setup wizard to use AI tax profile generation."
            )

        schema = TaxProfile.model_json_schema()
        system_prompt = TAX_PROFILE_SYSTEM_PROMPT.format(schema=json.dumps(schema, indent=2))
        user_prompt = (
            f"Generate the current stock market tax profile for: "
            f"{country_name} (country code: {country.value}). "
            f"Include all transaction taxes, capital gains rates, and relevant rules."
        )

        try:
            response = await self._llm.chat(system=system_prompt, user=user_prompt)
        except Exception as e:
            raise TaxGenerationError(f"LLM API call failed: {e}") from e

        # Parse and validate the response
        return self._parse_response(response, country)

    async def refresh(
        self, existing: TaxProfile, country_name: str
    ) -> TaxProfileDiff:
        """Refresh an existing tax profile and return the diff.

        Generates a new profile and compares it to the existing one,
        returning a structured diff for user review.

        Args:
            existing: Current tax profile
            country_name: Full country name

        Returns:
            TaxProfileDiff with old/new comparison
        """
        new_profile = await self.generate(existing.country, country_name)
        return TaxProfileDiff(
            country=existing.country,
            old_profile=existing,
            new_profile=new_profile,
            changes=self._compute_changes(existing, new_profile),
        )

    def generate_sync_fallback(self, country: Country) -> Optional[TaxProfile]:
        """Synchronous fallback that returns the built-in profile.

        Used when no LLM is available — returns None to signal that
        the pre-built profile should be used as-is.
        """
        return None

    # ── Internal ────────────────────────────────────────────────────────

    def _parse_response(self, response: str, country: Country) -> TaxProfile:
        """Parse and validate LLM response into a TaxProfile."""
        # Strip markdown code blocks if present
        cleaned = response.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            # Remove first and last lines (```json and ```)
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines)

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise TaxGenerationError(
                f"LLM returned invalid JSON: {e}\nResponse: {cleaned[:200]}..."
            ) from e

        # Ensure required fields
        data.setdefault("country", country.value)
        data.setdefault("source", "ai_generated")
        data.setdefault("verified_by_user", False)
        data.setdefault("last_updated", datetime.now(timezone.utc).strftime("%Y-%m-%d"))

        try:
            profile = TaxProfile.model_validate(data)
        except ValidationError as e:
            raise TaxGenerationError(
                f"LLM output failed Pydantic validation: {e}"
            ) from e

        return profile

    def _compute_changes(self, old: TaxProfile, new: TaxProfile) -> list[str]:
        """Compute human-readable list of changes between profiles."""
        changes = []

        if old.capital_gains_short_term_pct != new.capital_gains_short_term_pct:
            changes.append(
                f"Short-term CGT: {old.capital_gains_short_term_pct}% → {new.capital_gains_short_term_pct}%"
            )

        if old.capital_gains_long_term_pct != new.capital_gains_long_term_pct:
            changes.append(
                f"Long-term CGT: {old.capital_gains_long_term_pct}% → {new.capital_gains_long_term_pct}%"
            )

        if old.short_term_threshold_days != new.short_term_threshold_days:
            changes.append(
                f"LT threshold: {old.short_term_threshold_days} days → {new.short_term_threshold_days} days"
            )

        if old.wash_sale_rule != new.wash_sale_rule:
            changes.append(
                f"Wash sale rule: {old.wash_sale_rule} → {new.wash_sale_rule}"
            )

        # Compare transaction taxes
        old_names = {t.name for t in old.transaction_taxes}
        new_names = {t.name for t in new.transaction_taxes}

        added = new_names - old_names
        removed = old_names - new_names

        for name in added:
            changes.append(f"Added tax: {name}")
        for name in removed:
            changes.append(f"Removed tax: {name}")

        # Check rate changes for existing taxes
        old_by_name = {t.name: t for t in old.transaction_taxes}
        new_by_name = {t.name: t for t in new.transaction_taxes}

        for name in old_names & new_names:
            if old_by_name[name].rate_pct != new_by_name[name].rate_pct:
                changes.append(
                    f"{name}: {old_by_name[name].rate_pct}% → {new_by_name[name].rate_pct}%"
                )

        if not changes:
            changes.append("No changes detected")

        return changes


# ── Data Classes ────────────────────────────────────────────────────────────


class TaxProfileDiff:
    """Comparison between old and new tax profiles for user review."""

    def __init__(
        self,
        country: Country,
        old_profile: TaxProfile,
        new_profile: TaxProfile,
        changes: list[str],
    ):
        self.country = country
        self.old_profile = old_profile
        self.new_profile = new_profile
        self.changes = changes

    def to_dict(self) -> dict:
        """Serialize for API response."""
        return {
            "country": self.country.value,
            "changes": self.changes,
            "old_profile": self.old_profile.model_dump(),
            "new_profile": self.new_profile.model_dump(),
            "requires_user_verification": True,
        }


class TaxGenerationError(Exception):
    """Raised when AI tax profile generation fails."""
    pass
