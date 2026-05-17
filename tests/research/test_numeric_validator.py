"""Unit tests for the numeric validator (Task 11.1).

Exercises the locale-aware token grammar and the brief-vs-chunks
comparison loop across every shape called out in design §3.8:
``₹1,234.56``, ``1.2 Cr``, ``2.5 lakh``, ``2.5%``, ``FY24``,
``Q1 FY25``.

Property tests for the same module live in
``test_prop_numeric_fidelity.py`` (Task 11.4); this file targets the
specific examples the task description names, plus the edge cases
that shaped the parser design (grouping styles, currency-less
multipliers, fiscal-year pivot).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest

from src.research.validators.numeric_validator import (
    NumericValidator,
    extract_numeric_tokens,
    validate_numeric_fidelity,
)
from src.research.validators.types import UnsupportedClaim

# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _FakeChunk:
    """Duck-typed chunk — only ``.text`` is read by the validator."""

    text: str


# --------------------------------------------------------------------------- #
# Token extraction                                                            #
# --------------------------------------------------------------------------- #


class TestExtractNumericTokens:
    """The tokenizer handles every shape named in design §3.8."""

    def test_rupee_prefix(self) -> None:
        tokens = extract_numeric_tokens("Revenue was ₹1,234.56 in the quarter.")
        assert len(tokens) == 1
        token = tokens[0]
        assert token.value == Decimal("1234.56")
        assert token.unit == "INR"
        assert token.original_text == "₹1,234.56"

    def test_rs_dot_prefix(self) -> None:
        tokens = extract_numeric_tokens("Profit of Rs. 500 was reported.")
        assert len(tokens) == 1
        assert tokens[0].value == Decimal(500)
        assert tokens[0].unit == "INR"

    def test_crore_suffix_without_currency(self) -> None:
        tokens = extract_numeric_tokens("EBITDA of 1.2 Cr this quarter.")
        assert len(tokens) == 1
        assert tokens[0].value == Decimal(12000000)
        assert tokens[0].unit == "count_or_inr"

    def test_lakh_suffix_without_currency(self) -> None:
        tokens = extract_numeric_tokens("Order book is 2.5 lakh units.")
        assert len(tokens) == 1
        assert tokens[0].value == Decimal(250000)
        assert tokens[0].unit == "count_or_inr"

    def test_rupee_with_crore_suffix(self) -> None:
        tokens = extract_numeric_tokens("Revenue was ₹1,234.56 Cr.")
        assert len(tokens) == 1
        # 1,234.56 Cr → 12,345,600,000
        assert tokens[0].value == Decimal(12345600000)
        assert tokens[0].unit == "INR"

    def test_percent(self) -> None:
        tokens = extract_numeric_tokens("Growth of 2.5% year on year.")
        assert len(tokens) == 1
        assert tokens[0].value == Decimal("2.5")
        assert tokens[0].unit == "percent"

    def test_percent_word(self) -> None:
        tokens = extract_numeric_tokens("A 10 percent dividend was declared.")
        assert len(tokens) == 1
        assert tokens[0].value == Decimal(10)
        assert tokens[0].unit == "percent"

    def test_fiscal_year_two_digit(self) -> None:
        tokens = extract_numeric_tokens("Results for FY24 were strong.")
        assert len(tokens) == 1
        assert tokens[0].value == Decimal(2024)
        assert tokens[0].unit == "fiscal_year"

    def test_fiscal_year_four_digit(self) -> None:
        tokens = extract_numeric_tokens("Outlook for FY2025 remains positive.")
        assert len(tokens) == 1
        assert tokens[0].value == Decimal(2025)
        assert tokens[0].unit == "fiscal_year"

    def test_fiscal_quarter(self) -> None:
        tokens = extract_numeric_tokens("Q1 FY25 revenue beat estimates.")
        assert len(tokens) == 1
        assert tokens[0].value == Decimal(20251)  # fy*10 + quarter
        assert tokens[0].unit == "fiscal_quarter"

    def test_fiscal_quarter_no_space(self) -> None:
        tokens = extract_numeric_tokens("Q3FY26 guidance was maintained.")
        assert len(tokens) == 1
        assert tokens[0].value == Decimal(20263)

    def test_fiscal_range(self) -> None:
        tokens = extract_numeric_tokens("For 2023-24 the company reported growth.")
        assert len(tokens) == 1
        # 2023-24 → ending year 2024
        assert tokens[0].value == Decimal(2024)
        assert tokens[0].unit == "fiscal_year"

    def test_bare_number(self) -> None:
        tokens = extract_numeric_tokens("The book value is 25.5 per share.")
        # ``25.5`` is followed by whitespace so it qualifies as bare.
        values = [t.value for t in tokens]
        assert Decimal("25.5") in values

    def test_indian_grouping(self) -> None:
        tokens = extract_numeric_tokens("Revenue of ₹12,34,567 was recorded.")
        assert len(tokens) == 1
        assert tokens[0].value == Decimal(1234567)

    def test_fy_pivot_recent(self) -> None:
        """Two-digit FY below pivot resolves to 21st century."""
        tokens = extract_numeric_tokens("The FY49 outlook is speculative.")
        assert len(tokens) == 1
        assert tokens[0].value == Decimal(2049)

    def test_fy_pivot_legacy(self) -> None:
        """Two-digit FY at/above pivot resolves to 20th century."""
        tokens = extract_numeric_tokens("In FY99 the company went public.")
        assert len(tokens) == 1
        assert tokens[0].value == Decimal(1999)

    def test_multiple_tokens_preserved_in_order(self) -> None:
        text = "Revenue ₹1,234 Cr in FY24 grew 12.5% over Q1 FY23."
        tokens = extract_numeric_tokens(text)
        # Verify order follows source appearance.
        kinds = [t.unit for t in tokens]
        # ``₹1,234 Cr`` then ``FY24`` then ``12.5%`` then ``Q1 FY23``.
        assert kinds[0] == "INR"
        assert kinds[1] == "fiscal_year"
        assert kinds[2] == "percent"
        assert kinds[3] == "fiscal_quarter"

    def test_offsets_point_back_to_source(self) -> None:
        text = "Growth was 2.5% this year."
        tokens = extract_numeric_tokens(text)
        assert len(tokens) == 1
        token = tokens[0]
        assert text[token.start_offset : token.end_offset] == token.original_text

    def test_empty_text_returns_empty(self) -> None:
        assert extract_numeric_tokens("") == []

    def test_text_without_numbers_returns_empty(self) -> None:
        assert extract_numeric_tokens("No numeric content here.") == []


# --------------------------------------------------------------------------- #
# Validator behaviour                                                         #
# --------------------------------------------------------------------------- #


class TestNumericValidator:
    """End-to-end behaviour over brief + cited chunks."""

    def test_matching_number_is_supported(self) -> None:
        brief = {"financial_highlights": "Revenue was ₹1,234 Cr."}
        chunks = [_FakeChunk(text="Revenue for the period was ₹1,234 Cr.")]
        assert validate_numeric_fidelity(brief=brief, cited_chunks=chunks) == []

    def test_mismatched_number_is_flagged(self) -> None:
        brief = {"financial_highlights": "Revenue was ₹5,678 Cr."}
        chunks = [_FakeChunk(text="Revenue for the period was ₹1,234 Cr.")]
        violations = validate_numeric_fidelity(brief=brief, cited_chunks=chunks)
        assert len(violations) == 1
        v = violations[0]
        assert isinstance(v, UnsupportedClaim)
        assert v.reason == "numeric_drift"
        assert v.section == "financial_highlights"
        assert "5,678" in v.claim_text

    def test_cross_unit_magnitude_match(self) -> None:
        """``1.2 Cr`` in the brief matches ``12,000,000`` in a chunk."""
        brief = {"summary": "The order book grew to 1.2 Cr units."}
        chunks = [_FakeChunk(text="Order book: 12000000 units.")]
        assert validate_numeric_fidelity(brief=brief, cited_chunks=chunks) == []

    def test_relative_epsilon_accepts_small_rounding(self) -> None:
        """1% relative epsilon accepts ``1234.56`` vs ``1234.6``."""
        brief = {"summary": "Revenue was ₹1,234.56."}
        chunks = [_FakeChunk(text="Revenue was ₹1,234.6.")]
        assert validate_numeric_fidelity(brief=brief, cited_chunks=chunks) == []

    def test_relative_epsilon_rejects_large_drift(self) -> None:
        brief = {"summary": "Revenue was ₹1,234."}
        chunks = [_FakeChunk(text="Revenue was ₹1,500.")]
        violations = validate_numeric_fidelity(brief=brief, cited_chunks=chunks)
        assert len(violations) == 1

    def test_percent_only_matches_percent(self) -> None:
        """A bare ``2.5`` in a chunk does not satisfy ``2.5%`` in the brief."""
        brief = {"summary": "Margin was 2.5%."}
        chunks = [_FakeChunk(text="Margin ratio was 2.5.")]
        violations = validate_numeric_fidelity(brief=brief, cited_chunks=chunks)
        assert len(violations) == 1
        assert violations[0].reason == "numeric_drift"

    def test_fiscal_year_requires_exact_match(self) -> None:
        """FY24 does not satisfy FY23 even though years are close."""
        brief = {"summary": "FY24 was strong."}
        chunks = [_FakeChunk(text="FY23 was challenging.")]
        violations = validate_numeric_fidelity(brief=brief, cited_chunks=chunks)
        assert len(violations) == 1
        assert violations[0].claim_text == "FY24"

    def test_fiscal_quarter_requires_exact_match(self) -> None:
        brief = {"summary": "Q1 FY25 saw growth."}
        chunks = [_FakeChunk(text="Q2 FY25 saw growth.")]
        violations = validate_numeric_fidelity(brief=brief, cited_chunks=chunks)
        assert len(violations) == 1

    def test_multiple_sections_are_all_checked(self) -> None:
        brief = {
            "summary": "Revenue ₹1,234 Cr.",
            "risks": "Margin fell 5%.",
        }
        # Only the first claim is supported.
        chunks = [_FakeChunk(text="Revenue of ₹1,234 Cr reported.")]
        violations = validate_numeric_fidelity(brief=brief, cited_chunks=chunks)
        assert len(violations) == 1
        assert violations[0].section == "risks"

    def test_empty_brief_has_no_violations(self) -> None:
        assert validate_numeric_fidelity(brief={}, cited_chunks=[]) == []

    def test_empty_chunks_flag_every_token(self) -> None:
        brief = {"summary": "Revenue ₹1,234 Cr and margin of 10%."}
        violations = validate_numeric_fidelity(brief=brief, cited_chunks=[])
        # Two tokens: ``₹1,234 Cr`` and ``10%``.
        assert len(violations) == 2

    def test_duck_typed_brief_object(self) -> None:
        """Any object exposing section attributes is accepted."""

        class BriefLike:
            summary = "Revenue ₹100 Cr."
            thesis = ""
            risks = ""
            financial_highlights = ""
            management_commentary = ""
            technical_view = ""
            peers = ""
            macro_context = ""

        chunks = [_FakeChunk(text="Reported revenue ₹100 Cr.")]
        assert validate_numeric_fidelity(brief=BriefLike(), cited_chunks=chunks) == []

    def test_constructor_epsilon_override(self) -> None:
        """Constructor-supplied epsilon overrides the default."""
        brief = {"summary": "Revenue ₹1,000."}
        chunks = [_FakeChunk(text="Revenue ₹1,050.")]
        # 5% drift — default 1% rejects, 10% accepts.
        assert NumericValidator(epsilon=0.01).validate(
            brief=brief,
            cited_chunks=chunks,
        )
        assert (
            NumericValidator(epsilon=0.10).validate(
                brief=brief,
                cited_chunks=chunks,
            )
            == []
        )

    def test_epsilon_negative_raises(self) -> None:
        with pytest.raises(ValueError):
            NumericValidator(epsilon=-0.1)

    def test_offset_spans_map_back_to_section_text(self) -> None:
        content = "Revenue was ₹5,678 Cr this period."
        brief = {"financial_highlights": content}
        chunks = [_FakeChunk(text="Unrelated content.")]
        violations = validate_numeric_fidelity(brief=brief, cited_chunks=chunks)
        assert len(violations) == 1
        v = violations[0]
        assert content[v.start_offset : v.end_offset] == v.claim_text
