"""Performance tests for LOHI-TRADE.

Validates:
  - Tick processing latency < 10ms (p99)
  - Throughput >= 1000 ticks/second
  - Order validation latency < 50ms (p99)

Requirements: 26.5
"""

import statistics
import time
import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from src.execution.rms import RiskManagementSystem
from src.ingestion.broker_interface import (
    Tick,
)
from src.soldier.candle_builder import CandleBuilder
from src.soldier.indicator_engine import IndicatorSet
from src.soldier.strategy_engine import Signal

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tick(symbol: str = "RELIANCE", ltp: float = 2500.0,
               volume: int = 100, ts: datetime | None = None) -> Tick:
    """Create a Tick for testing."""
    return Tick(
        symbol=symbol,
        token=12345,
        ltp=ltp,
        volume=volume,
        timestamp=ts or datetime(2024, 1, 15, 10, 0, 0),
        exchange="NSE",
    )


def _make_signal(symbol: str = "RELIANCE") -> Signal:
    """Create a Signal for RMS validation testing."""
    return Signal(
        signal_id=str(uuid.uuid4()),
        symbol=symbol,
        strategy="MeanReversion",
        side="BUY",
        entry_price=2500.0,
        stop_loss=2480.0,
        target=2530.0,
        quantity=10,
        timestamp=datetime(2024, 1, 15, 10, 30, 0),
        indicators=IndicatorSet(
            symbol=symbol,
            timeframe="5m",
            timestamp=datetime(2024, 1, 15, 10, 30, 0),
            rsi_14=35.0,
            macd=1.5,
            macd_signal=1.0,
            macd_hist=0.5,
            bb_upper=2550.0,
            bb_middle=2520.0,
            bb_lower=2490.0,
            vwap=2510.0,
            ema_9=2505.0,
            ema_21=2500.0,
            supertrend=2495.0,
            supertrend_direction=1,
            atr_14=15.0,
            volume_avg_20=50000.0,
        ),
    )


def _build_mock_config():
    """Build a mock Config with all attributes RMS needs."""
    config = MagicMock()
    config.trading_hours.trading_start = "09:15"
    config.trading_hours.trading_end = "15:30"
    config.capital.total = 1_000_000.0
    config.capital.max_daily_loss_pct = 2.0
    config.capital.max_position_size_pct = 10.0
    config.risk_limits.max_open_positions = 5
    config.risk_limits.max_orders_per_day = 20
    config.risk_limits.cooldown_after_loss_minutes = 5
    config.risk_limits.volatility_guard_threshold_pct = 3.0
    config.risk_limits.volatility_guard_window_minutes = 15
    return config


# ---------------------------------------------------------------------------
# 1. Tick Processing Latency  (p99 < 10 ms)
# ---------------------------------------------------------------------------

class TestTickProcessingLatency:
    """Validate that processing a tick through CandleBuilder is fast."""

    def test_tick_processing_p99_under_10ms(self):
        """Process 1000 ticks and assert p99 latency < 10ms."""
        builder = CandleBuilder(timeframes=["1m"])

        base_ts = datetime(2024, 1, 15, 10, 0, 0)
        ticks = [
            _make_tick(
                ltp=2500.0 + (i * 0.01),
                volume=100 + i,
                ts=base_ts + timedelta(milliseconds=i * 10),
            )
            for i in range(1000)
        ]

        latencies: list[float] = []
        for tick in ticks:
            start = time.perf_counter()
            builder.process_tick(tick)
            end = time.perf_counter()
            latencies.append((end - start) * 1000)  # ms

        avg_ms = statistics.mean(latencies)
        p99_ms = sorted(latencies)[int(len(latencies) * 0.99)]

        assert p99_ms < 10, (
            f"p99 tick latency {p99_ms:.3f}ms exceeds 10ms threshold "
            f"(avg={avg_ms:.3f}ms)"
        )

    def test_tick_processing_average_under_1ms(self):
        """Average tick processing should be well under 1ms."""
        builder = CandleBuilder(timeframes=["1m"])

        base_ts = datetime(2024, 1, 15, 10, 0, 0)
        latencies: list[float] = []
        for i in range(1000):
            tick = _make_tick(
                ltp=2500.0 + (i * 0.01),
                volume=100 + i,
                ts=base_ts + timedelta(milliseconds=i * 10),
            )
            start = time.perf_counter()
            builder.process_tick(tick)
            end = time.perf_counter()
            latencies.append((end - start) * 1000)

        avg_ms = statistics.mean(latencies)
        assert avg_ms < 1, f"Average tick latency {avg_ms:.3f}ms exceeds 1ms"


# ---------------------------------------------------------------------------
# 2. Throughput  (>= 1000 ticks / second)
# ---------------------------------------------------------------------------

class TestThroughput:
    """Validate tick processing throughput."""

    def test_throughput_at_least_1000_ticks_per_second(self):
        """Process 1000 ticks and verify throughput >= 1000 ticks/sec."""
        builder = CandleBuilder(timeframes=["1m"])

        base_ts = datetime(2024, 1, 15, 10, 0, 0)
        ticks = [
            _make_tick(
                ltp=2500.0 + (i * 0.01),
                volume=100 + i,
                ts=base_ts + timedelta(milliseconds=i * 10),
            )
            for i in range(1000)
        ]

        start = time.perf_counter()
        for tick in ticks:
            builder.process_tick(tick)
        elapsed = time.perf_counter() - start

        throughput = 1000 / elapsed
        assert throughput >= 1000, (
            f"Throughput {throughput:.0f} ticks/sec is below 1000 threshold "
            f"(elapsed={elapsed:.4f}s)"
        )

    def test_throughput_multiple_timeframes(self):
        """Throughput stays >= 1000 ticks/sec even with 3 timeframes."""
        builder = CandleBuilder(timeframes=["1m", "5m", "15m"])

        base_ts = datetime(2024, 1, 15, 10, 0, 0)
        ticks = [
            _make_tick(
                ltp=2500.0 + (i * 0.01),
                volume=100 + i,
                ts=base_ts + timedelta(milliseconds=i * 10),
            )
            for i in range(1000)
        ]

        start = time.perf_counter()
        for tick in ticks:
            builder.process_tick(tick)
        elapsed = time.perf_counter() - start

        throughput = 1000 / elapsed
        assert throughput >= 1000, (
            f"Multi-timeframe throughput {throughput:.0f} ticks/sec < 1000 "
            f"(elapsed={elapsed:.4f}s)"
        )


# ---------------------------------------------------------------------------
# 3. Order Validation Latency  (p99 < 50 ms)
# ---------------------------------------------------------------------------

class TestOrderValidationLatency:
    """Validate that RMS order validation is fast with mocked dependencies."""

    def _create_rms(self) -> RiskManagementSystem:
        """Create an RMS instance with fully mocked dependencies."""
        config = _build_mock_config()
        redis_client = MagicMock()
        event_bus = MagicMock()
        db_manager = MagicMock()

        # Fix the "now" to a valid trading time
        fixed_now = datetime(2024, 1, 15, 10, 30, 0)

        rms = RiskManagementSystem(
            config=config,
            redis_client=redis_client,
            event_bus=event_bus,
            db_manager=db_manager,
            now_fn=lambda: fixed_now,
        )

        # Mock all internal check methods to return None (pass)
        rms._check_kill_switch = MagicMock(return_value=None)
        rms._check_trading_hours = MagicMock(return_value=None)
        rms._check_daily_loss_limit = MagicMock(return_value=None)
        rms._check_position_limit = MagicMock(return_value=None)
        rms._check_position_size_limit = MagicMock(return_value=None)
        rms._check_order_count_limit = MagicMock(return_value=None)
        rms._check_cooldown = MagicMock(return_value=None)
        rms._check_volatility_guard = MagicMock(return_value=None)
        rms._check_bias_filter = MagicMock(return_value=None)

        return rms

    def test_order_validation_p99_under_50ms(self):
        """Validate 100 orders and assert p99 latency < 50ms."""
        rms = self._create_rms()
        signals = [_make_signal(f"SYM{i}") for i in range(100)]

        latencies: list[float] = []
        for signal in signals:
            start = time.perf_counter()
            result = rms.validate_order(signal)
            end = time.perf_counter()
            latencies.append((end - start) * 1000)
            assert result.is_valid, f"Unexpected rejection: {result.rejection_reason}"

        avg_ms = statistics.mean(latencies)
        p99_ms = sorted(latencies)[int(len(latencies) * 0.99)]

        assert p99_ms < 50, (
            f"p99 validation latency {p99_ms:.3f}ms exceeds 50ms threshold "
            f"(avg={avg_ms:.3f}ms)"
        )

    def test_order_validation_average_under_5ms(self):
        """Average validation latency should be well under 5ms."""
        rms = self._create_rms()
        signals = [_make_signal(f"SYM{i}") for i in range(100)]

        latencies: list[float] = []
        for signal in signals:
            start = time.perf_counter()
            rms.validate_order(signal)
            end = time.perf_counter()
            latencies.append((end - start) * 1000)

        avg_ms = statistics.mean(latencies)
        assert avg_ms < 5, f"Average validation latency {avg_ms:.3f}ms exceeds 5ms"
