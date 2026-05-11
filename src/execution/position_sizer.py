"""Position Sizer for LOHI-TRADE.

Calculates order quantity based on risk per trade, enforcing maximum risk
and position size limits. Rejects orders when calculated quantity is below 1.

Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.7
"""

from dataclasses import dataclass

from src.soldier.strategy_engine import Signal
from src.utils.config import Config
from src.utils.logger import get_logger

logger = get_logger("PositionSizer")


@dataclass
class PositionSizeResult:
    """Result of a position size calculation.

    Attributes:
        quantity: Number of shares (0 if invalid).
        is_valid: Whether the calculated quantity is tradeable.
        rejection_reason: Reason for rejection, if any.
        risk_amount: Actual risk = quantity * (entry_price - stop_loss).
        position_value: Total position value = quantity * entry_price.

    """

    quantity: int
    is_valid: bool
    rejection_reason: str | None
    risk_amount: float
    position_value: float


class PositionSizer:
    """Calculate position sizes based on risk management rules.

    Uses the formula: quantity = (capital × risk_pct / 100) / (entry_price - stop_loss)
    Then caps by max position size and rounds to nearest integer.
    """

    def __init__(self, config: Config) -> None:
        self._capital = config.capital.total
        self._risk_per_trade_pct = config.capital.risk_per_trade_pct
        self._max_position_size_pct = config.capital.max_position_size_pct

    def calculate_quantity(self, signal: Signal) -> PositionSizeResult:
        """Calculate the position size for a given signal.

        Steps:
            1. Calculate risk per share: entry_price - stop_loss
            2. Calculate max risk amount: capital * risk_per_trade_pct / 100
            3. Calculate raw quantity: max_risk_amount / risk_per_share
            4. Cap by max position size: min(quantity, max_position_value / entry_price)
            5. Round to nearest integer
            6. Reject if quantity < 1

        Args:
            signal: The trading signal with entry_price and stop_loss.

        Returns:
            PositionSizeResult with calculated quantity and validity.

        """
        risk_per_share = abs(signal.entry_price - signal.stop_loss)

        if risk_per_share <= 0:
            logger.warning(
                f"Zero risk per share for {signal.symbol}: entry={signal.entry_price:.2f} stop={signal.stop_loss:.2f}",
            )
            return PositionSizeResult(
                quantity=0,
                is_valid=False,
                rejection_reason="Risk per share is zero (entry equals stop loss)",
                risk_amount=0.0,
                position_value=0.0,
            )

        # Step 1-2: max risk amount
        max_risk_amount = self._capital * self._risk_per_trade_pct / 100.0

        # Step 3: raw quantity from risk formula
        raw_quantity = max_risk_amount / risk_per_share

        # Step 4: cap by max position size
        max_position_value = self._capital * self._max_position_size_pct / 100.0
        max_qty_by_position = max_position_value / signal.entry_price
        capped_quantity = min(raw_quantity, max_qty_by_position)

        # Step 5: round to nearest integer
        quantity = round(capped_quantity)

        # Step 6: reject if < 1
        if quantity < 1:
            logger.info(
                f"Position size too small for {signal.symbol}: calculated={capped_quantity:.2f}, rounded={quantity}",
            )
            return PositionSizeResult(
                quantity=0,
                is_valid=False,
                rejection_reason="Insufficient capital for minimum quantity",
                risk_amount=0.0,
                position_value=0.0,
            )

        risk_amount = quantity * risk_per_share
        position_value = quantity * signal.entry_price

        logger.info(
            f"Position sized for {signal.symbol}: qty={quantity}, risk={risk_amount:.2f}, value={position_value:.2f}",
        )

        return PositionSizeResult(
            quantity=quantity,
            is_valid=True,
            rejection_reason=None,
            risk_amount=risk_amount,
            position_value=position_value,
        )
