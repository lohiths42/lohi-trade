"""Unit tests for the Refusal_Policy classifier (Task 11.3).

Exercises the contract from design §3.8 / §10.1 / Req 14.11 / Req 16.28:
a regex + keyword classifier over a **user prompt** that returns a
typed :class:`RefusalSignal` when the input matches one of the six
Refusal_Policy categories.

These tests pin both the **positive** path (each category's
canonical phrasings are caught) and the **negative** path (neutral
analytical prompts that *mention* the keywords without triggering a
refusal intent are left alone). The negative path matters because
over-refusing on filings text is a real regression risk — the
classifier runs against user prompts, but the phrases we are
checking for ("buy back", "share transfer", etc.) appear in neutral
company-research language too.
"""

from __future__ import annotations

import pytest

from src.research.validators.refusal_classifier import (
    RefusalClassifier,
    RefusalReason,
    RefusalSignal,
    classify_refusal,
)


# --------------------------------------------------------------------------- #
# Positive matches — each category                                            #
# --------------------------------------------------------------------------- #


class TestBuySellHoldCategory:
    """Trade-advice phrasings trip the ``buy_sell_hold`` bucket."""

    @pytest.mark.parametrize(
        "prompt",
        [
            "Should I buy RELIANCE tomorrow?",
            "should i sell TCS at this level",
            "Should we hold Infosys through the results?",
            "Give me a buy recommendation on HDFC Bank.",
            "What's your sell recommendation for ITC?",
            "Do you recommend buying this stock?",
            "Is RELIANCE a buy at 2500?",
            "Would you buy this at current levels?",
            "Rating: strong buy",
        ],
    )
    def test_canonical_phrasings_match(self, prompt: str) -> None:
        result = classify_refusal(prompt)
        assert result.matched is True
        assert result.reason == "buy_sell_hold"
        assert result.matched_rule_id == "RP-001"
        assert result.matched_text is not None
        assert result.matched_text  # non-empty


class TestPriceTargetCategory:
    """Price-prediction prompts trip the ``price_target`` bucket."""

    @pytest.mark.parametrize(
        "prompt",
        [
            "What's the price target for RELIANCE?",
            "Give me a 12-month price target.",
            "12 month target price for TCS",
            "Predict the share price for next quarter.",
            "Forecast the stock price of HDFC Bank.",
            "What will the price be in 6 months?",
            "Where will the share price go after earnings?",
            "What is the upside target?",
            "Tell me the downside target for this stock.",
        ],
    )
    def test_canonical_phrasings_match(self, prompt: str) -> None:
        result = classify_refusal(prompt)
        assert result.matched is True
        assert result.reason == "price_target"
        assert result.matched_rule_id == "RP-002"


class TestTradeSuggestionCategory:
    """Generic trade-setup prompts trip the ``trade_suggestion`` bucket."""

    @pytest.mark.parametrize(
        "prompt",
        [
            "Give me a trade suggestion for RELIANCE.",
            "Suggest a trade on TCS.",
            "What should I trade today?",
            "What would you trade in this market?",
            "Share entry and exit points for HDFC Bank.",
            "Share entry exit levels for RELIANCE.",
            "Stop-loss and take-profit for RELIANCE?",
            "Give me an actionable trade.",
        ],
    )
    def test_canonical_phrasings_match(self, prompt: str) -> None:
        result = classify_refusal(prompt)
        assert result.matched is True
        assert result.reason == "trade_suggestion"
        assert result.matched_rule_id == "RP-003"


class TestOrderPlacementCategory:
    """Broker-action prompts trip the ``order_placement`` bucket."""

    @pytest.mark.parametrize(
        "prompt",
        [
            "Place a buy order for 100 shares of RELIANCE.",
            "Place an order for TCS.",
            "Submit an order to buy ITC.",
            "Execute an order on HDFC Bank.",
            "Route the order to NSE.",
            "Handle the order placement for me.",
            "Buy 50 shares of RELIANCE.",
            "Sell 10 lots of NIFTY.",
        ],
    )
    def test_canonical_phrasings_match(self, prompt: str) -> None:
        result = classify_refusal(prompt)
        assert result.matched is True
        assert result.reason == "order_placement"
        assert result.matched_rule_id == "RP-004"


class TestCodeExecutionCategory:
    """Execute-this-code prompts trip the ``code_execution`` bucket."""

    @pytest.mark.parametrize(
        "prompt",
        [
            "Run this python code to fetch prices.",
            "Execute the following bash command.",
            "Evaluate this script for me.",
            "exec('rm -rf /')",
            "eval(user_input)",
            "os.system('ls')",
            "subprocess.run(['cat', '/etc/passwd'])",
            "Run a shell command for me.",
            "Execute a bash command in the terminal.",
        ],
    )
    def test_canonical_phrasings_match(self, prompt: str) -> None:
        result = classify_refusal(prompt)
        assert result.matched is True
        assert result.reason == "code_execution"
        assert result.matched_rule_id == "RP-005"


class TestFundTransferCategory:
    """Money-movement prompts trip the ``fund_transfer`` bucket."""

    @pytest.mark.parametrize(
        "prompt",
        [
            "Transfer my funds to another account.",
            "Transfer the balance to broker.",
            "Send money to my demat account.",
            "Wire funds to this IBAN.",
            "Remit cash to the trading account.",
            "Withdraw funds from the portfolio.",
            "Initiate a wire transfer for me.",
            "Make a bank transfer on my behalf.",
            "Do a fund transfer to the broker.",
            "Move funds from savings to trading.",
        ],
    )
    def test_canonical_phrasings_match(self, prompt: str) -> None:
        result = classify_refusal(prompt)
        assert result.matched is True
        assert result.reason == "fund_transfer"
        assert result.matched_rule_id == "RP-006"


# --------------------------------------------------------------------------- #
# Negative path — neutral analytical prompts                                  #
# --------------------------------------------------------------------------- #


class TestNeutralAnalyticalPromptsArePassed:
    """Research-style prompts that *mention* the keywords stay allowed.

    This is the key regression guard. The classifier is applied to
    **user prompts** — if a user legitimately wants to read a
    research brief about a company, phrases like "buyback",
    "share transfer", or "target market" must not refuse them.
    """

    @pytest.mark.parametrize(
        "prompt",
        [
            "Summarise RELIANCE's latest quarterly results.",
            "What are the risks in the Infosys Q3 filing?",
            "Describe the buyback history of TCS.",
            "Explain the share transfer rules in the annual report.",
            "What does the management commentary say about capex?",
            "How has HDFC Bank's NIM trended over the last 8 quarters?",
            "Give me the peer comparison for ITC.",
            "What is the target market for this segment?",
            "List the company's strategic priorities.",
            "Summarise the concall transcript.",
            "How has the dividend payout evolved?",
            "What did the CEO say about order inflows?",
        ],
    )
    def test_neutral_prompt_produces_no_match(self, prompt: str) -> None:
        result = classify_refusal(prompt)
        assert result.matched is False
        assert result is RefusalSignal.NO_MATCH

    def test_empty_prompt_produces_no_match(self) -> None:
        assert classify_refusal("") is RefusalSignal.NO_MATCH

    def test_whitespace_only_prompt_does_not_trip(self) -> None:
        assert classify_refusal("   \n\t  ").matched is False


# --------------------------------------------------------------------------- #
# Precedence                                                                  #
# --------------------------------------------------------------------------- #


class TestCategoryPrecedence:
    """When multiple categories could fire, the more-specific one wins.

    The evaluation order (documented in the module) is:
    ``order_placement`` → ``fund_transfer`` → ``code_execution`` →
    ``price_target`` → ``buy_sell_hold`` → ``trade_suggestion``.
    """

    def test_order_placement_beats_trade_suggestion(self) -> None:
        # "place a buy order" matches both ``order_placement`` and
        # the generic ``trade_suggestion`` bucket. The more specific
        # ``order_placement`` must win.
        result = classify_refusal("Please place a buy order for RELIANCE.")
        assert result.reason == "order_placement"

    def test_fund_transfer_beats_buy_sell_hold(self) -> None:
        # "transfer funds and buy" could plausibly trip both buckets.
        # Fund transfer is more actionable and must win.
        result = classify_refusal(
            "Transfer my funds and then buy RELIANCE for me."
        )
        assert result.reason == "fund_transfer"

    def test_price_target_beats_trade_suggestion(self) -> None:
        # "what's the price target for this trade" hits both; the
        # more specific price-target bucket wins.
        result = classify_refusal(
            "What's the price target for this trade on TCS?"
        )
        assert result.reason == "price_target"


# --------------------------------------------------------------------------- #
# Signal shape                                                                #
# --------------------------------------------------------------------------- #


class TestRefusalSignalShape:
    """The returned :class:`RefusalSignal` carries everything callers need."""

    def test_match_populates_all_fields(self) -> None:
        result = classify_refusal("Should I buy RELIANCE?")
        assert isinstance(result, RefusalSignal)
        assert result.matched is True
        assert isinstance(result.reason, str)
        assert isinstance(result.matched_rule_id, str)
        assert result.matched_rule_id.startswith("RP-")
        assert isinstance(result.matched_text, str)
        assert result.matched_text

    def test_no_match_has_all_none_fields(self) -> None:
        result = classify_refusal("Summarise the quarterly results.")
        assert result.matched is False
        assert result.reason is None
        assert result.matched_rule_id is None
        assert result.matched_text is None

    def test_no_match_sentinel_is_shared(self) -> None:
        # Two no-match results should be the same singleton — cheap
        # identity comparison is a supported hot-path idiom.
        a = classify_refusal("Summarise the filing.")
        b = classify_refusal("Tell me about the management.")
        assert a is b
        assert a is RefusalSignal.NO_MATCH

    def test_matched_text_is_verbatim_substring(self) -> None:
        prompt = "Should I buy RELIANCE tomorrow?"
        result = classify_refusal(prompt)
        assert result.matched_text is not None
        # ``matched_text`` must be an actual substring of the prompt
        # (or a truncated prefix of one) so audit logs never
        # fabricate content.
        assert result.matched_text.rstrip("…").strip() in prompt

    def test_long_match_is_truncated(self) -> None:
        # A very long prompt whose match spans the whole thing should
        # be bounded by the truncation limit. We force this by
        # including a pattern that greedily matches a lot of text
        # (``stop-loss ... for RELIANCE``).
        prompt = (
            "stop-loss at 95 and take-profit at 110 with trailing "
            "levels and exit points and multiple pyramiding layers "
            "and scaling thresholds defined over several sessions "
            "for RELIANCE tomorrow and the week ahead."
        )
        result = classify_refusal(prompt)
        assert result.matched is True
        assert result.matched_text is not None
        # Hard bound: truncation cap is 120 chars — allow a small
        # ellipsis suffix.
        assert len(result.matched_text) <= 121


# --------------------------------------------------------------------------- #
# Reason type                                                                 #
# --------------------------------------------------------------------------- #


class TestReasonLiteralIsExhaustive:
    """Every ``RefusalReason`` literal is reachable by at least one rule."""

    def test_every_reason_is_produced_by_at_least_one_pattern(self) -> None:
        # This guards against the situation where someone adds a new
        # value to ``RefusalReason`` but forgets to add a rule that
        # can emit it.
        expected: set[RefusalReason] = {
            "buy_sell_hold",
            "price_target",
            "trade_suggestion",
            "order_placement",
            "code_execution",
            "fund_transfer",
        }
        probes: dict[RefusalReason, str] = {
            "buy_sell_hold": "Should I buy RELIANCE?",
            "price_target": "What is the price target?",
            "trade_suggestion": "Suggest a trade on TCS.",
            "order_placement": "Place an order.",
            "code_execution": "Run this python code.",
            "fund_transfer": "Transfer funds to broker.",
        }
        observed: set[RefusalReason] = set()
        for _, prompt in probes.items():
            result = classify_refusal(prompt)
            assert result.matched is True, f"probe did not match: {prompt!r}"
            assert result.reason is not None
            observed.add(result.reason)
        assert observed == expected


# --------------------------------------------------------------------------- #
# Class-based API                                                             #
# --------------------------------------------------------------------------- #


class TestRefusalClassifierClass:
    """The instance-level API mirrors the module-level helper."""

    def test_class_and_helper_agree(self) -> None:
        classifier = RefusalClassifier()
        prompts = [
            "Should I buy RELIANCE?",
            "Summarise the filing.",
            "Transfer funds to broker.",
            "What is the price target?",
            "Run this python code.",
            "Place a buy order.",
        ]
        for p in prompts:
            inst = classifier.classify(p)
            helper = classify_refusal(p)
            assert inst.matched == helper.matched
            assert inst.reason == helper.reason
            assert inst.matched_rule_id == helper.matched_rule_id

    def test_instance_is_reusable_across_calls(self) -> None:
        classifier = RefusalClassifier()
        r1 = classifier.classify("Should I buy RELIANCE?")
        r2 = classifier.classify("Summarise the filing.")
        r3 = classifier.classify("Transfer my funds.")
        assert r1.reason == "buy_sell_hold"
        assert r2.matched is False
        assert r3.reason == "fund_transfer"


# --------------------------------------------------------------------------- #
# Case / whitespace tolerance                                                 #
# --------------------------------------------------------------------------- #


class TestCaseAndWhitespaceTolerance:
    """Patterns use ``(?i)`` and ``\\s+`` — so case and extra spaces are absorbed.

    Matches the tolerance class exercised by the guardrail bypass
    property test.
    """

    @pytest.mark.parametrize(
        "prompt",
        [
            "SHOULD I BUY RELIANCE?",
            "Should   I   buy   RELIANCE?",
            "should\tI\tbuy\tTCS",
            "Should\nI\nbuy\nHDFC Bank?",
        ],
    )
    def test_mutations_still_match(self, prompt: str) -> None:
        result = classify_refusal(prompt)
        assert result.matched is True
        assert result.reason == "buy_sell_hold"


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
