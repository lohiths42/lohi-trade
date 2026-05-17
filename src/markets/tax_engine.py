"""Tax Engine — calculates estimated transaction charges and capital gains.

Provides charge estimation for order tickets (pre-trade) and P&L reports
(post-trade). Uses the active market's TaxProfile for calculations.

IMPORTANT: These are ESTIMATES for display purposes only. They are NOT
suitable for official tax filing. Users must consult tax professionals.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .market_profile import MarketProfile, TaxRule

logger = logging.getLogger(__name__)


@dataclass
class TaxEstimate:
    """Estimated charges for a single trade."""

    trade_value: float
    currency: str
    charges: list[ChargeItem]
    total_charges: float
    effective_rate_pct: float
    net_value: float  # trade_value - total_charges (for sells) or + (for buys)
    disclaimer: str


@dataclass
class ChargeItem:
    """A single charge line item."""

    name: str
    amount: float
    rate_pct: float
    description: str


@dataclass
class CapitalGainsEstimate:
    """Estimated capital gains tax for a realized trade."""

    gain_amount: float
    holding_days: int
    is_long_term: bool
    tax_rate_pct: float
    estimated_tax: float
    wash_sale_applicable: bool
    currency: str
    disclaimer: str


class TaxEngine:
    """Calculates transaction charges and capital gains estimates.

    Uses the market profile's tax rules to compute charges. All calculations
    are estimates — actual charges may vary based on broker-specific fees,
    tax bracket, and other factors.
    """

    def __init__(self, market_profile: MarketProfile):
        self._profile = market_profile
        self._tax = market_profile.tax_profile

    @property
    def currency(self) -> str:
        return self._tax.currency

    def estimate_transaction_charges(
        self,
        trade_value: float,
        side: str,
        is_intraday: bool = False,
        brokerage_amount: float = 0.0,
    ) -> TaxEstimate:
        """Estimate all transaction charges for a trade.

        Args:
            trade_value: Total trade value in local currency
            side: "buy" or "sell"
            is_intraday: Whether this is an intraday (day trade) position
            brokerage_amount: Broker commission amount (for GST/VAT calculation)

        Returns:
            TaxEstimate with itemized charges

        """
        charges: list[ChargeItem] = []
        total = 0.0

        for rule in self._tax.transaction_taxes:
            amount = self._apply_rule(rule, trade_value, side, is_intraday, brokerage_amount)
            if amount > 0:
                charges.append(
                    ChargeItem(
                        name=rule.name,
                        amount=round(amount, 4),
                        rate_pct=rule.rate_pct,
                        description=rule.description,
                    )
                )
                total += amount

        total = round(total, 2)
        effective_rate = (total / trade_value * 100) if trade_value > 0 else 0.0

        # Net value: for buys, you pay more; for sells, you receive less
        if side.lower() == "buy":
            net_value = trade_value + total
        else:
            net_value = trade_value - total

        return TaxEstimate(
            trade_value=trade_value,
            currency=self._tax.currency,
            charges=charges,
            total_charges=total,
            effective_rate_pct=round(effective_rate, 4),
            net_value=round(net_value, 2),
            disclaimer=self._tax.disclaimer,
        )

    def estimate_capital_gains_tax(
        self,
        buy_value: float,
        sell_value: float,
        holding_days: int,
    ) -> CapitalGainsEstimate:
        """Estimate capital gains tax for a realized position.

        Args:
            buy_value: Total purchase cost
            sell_value: Total sale proceeds
            holding_days: Number of days the position was held

        Returns:
            CapitalGainsEstimate with tax calculation

        """
        gain = sell_value - buy_value

        # Determine if long-term based on country's threshold
        threshold = self._tax.short_term_threshold_days
        is_long_term = holding_days >= threshold if threshold > 0 else False

        if is_long_term:
            rate = self._tax.capital_gains_long_term_pct
        else:
            rate = self._tax.capital_gains_short_term_pct

        # Only tax positive gains
        estimated_tax = max(0, gain * rate / 100) if gain > 0 else 0.0

        return CapitalGainsEstimate(
            gain_amount=round(gain, 2),
            holding_days=holding_days,
            is_long_term=is_long_term,
            tax_rate_pct=rate,
            estimated_tax=round(estimated_tax, 2),
            wash_sale_applicable=self._tax.wash_sale_rule,
            currency=self._tax.currency,
            disclaimer=self._tax.disclaimer,
        )

    def get_wash_sale_window(self) -> int:
        """Get the wash sale window in days (0 if not applicable)."""
        return self._tax.wash_sale_window_days

    def has_wash_sale_rule(self) -> bool:
        """Whether the market has wash sale / superficial loss rules."""
        return self._tax.wash_sale_rule

    # ── Internal ────────────────────────────────────────────────────────

    def _apply_rule(
        self,
        rule: TaxRule,
        trade_value: float,
        side: str,
        is_intraday: bool,
        brokerage_amount: float,
    ) -> float:
        """Apply a single tax rule and return the charge amount."""
        side_lower = side.lower()

        # Check if rule applies to this side/type
        if not self._rule_applies(rule, side_lower, is_intraday):
            return 0.0

        # Check threshold
        if rule.threshold and trade_value < rule.threshold:
            return 0.0

        # Calculate amount
        if rule.is_flat_fee:
            return rule.flat_fee_amount or 0.0

        # Special case: tax on brokerage (like GST on brokerage in India)
        if rule.applies_to == "brokerage":
            return brokerage_amount * rule.rate_pct / 100

        return trade_value * rule.rate_pct / 100

    def _rule_applies(self, rule: TaxRule, side: str, is_intraday: bool) -> bool:
        """Check if a tax rule applies to the given trade parameters."""
        applies = rule.applies_to.lower()

        if applies == "both":
            return True
        if applies == "buy" and side == "buy":
            return True
        if applies == "sell" and side == "sell":
            return True
        if applies == "intraday" and is_intraday and side == "sell":
            return True
        if applies == "delivery" and not is_intraday:
            return True
        if applies == "brokerage":
            return True

        return False
