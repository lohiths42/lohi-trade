#!/usr/bin/env python3
"""
Checkpoint 15: Verify Technical Analysis Pipeline

Verifies:
1. Candles are built correctly from ticks
2. Indicators are calculated correctly
3. Signals are generated for Mean Reversion strategy
4. No signals outside trading hours (trading hours filter not yet implemented)
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ingestion.broker_interface import Tick
from src.soldier.candle_builder import CandleBuilder, Candle
from src.soldier.indicator_engine import IndicatorEngine, IndicatorSet
from src.soldier.strategy_engine import MeanReversionStrategy
from src.utils.config import MeanReversionStrategy as MeanRevConfig


def make_tick(symbol: str, price: float, volume: int, ts: datetime) -> Tick:
    return Tick(
        symbol=symbol, token=1234, ltp=price,
        volume=volume, timestamp=ts, exchange="NSE",
    )


def verify_candle_building():
    """Verify candles are built correctly from ticks."""
    print("=" * 60)
    print("1. CANDLE BUILDING VERIFICATION")
    print("=" * 60)

    builder = CandleBuilder(timeframes=["1m"])
    completed = []
    builder.on_candle_complete(lambda c: completed.append(c))

    base = datetime(2025, 1, 6, 9, 15, 0)
    prices = [100.0, 102.0, 98.0, 101.0]
    volumes = [1000, 1500, 800, 1200]

    # Feed ticks within a single 1m candle
    for i, (p, v) in enumerate(zip(prices, volumes)):
        tick = make_tick("RELIANCE", p, v, base + timedelta(seconds=i * 10))
        builder.process_tick(tick)

    # Flush to complete the candle
    candles = builder.flush()

    if not candles:
        print("  FAIL: No candles produced after flush")
        return False

    c = candles[0]
    checks = [
        ("Open == first tick", c.open == 100.0),
        ("High == max tick", c.high == 102.0),
        ("Low == min tick", c.low == 98.0),
        ("Close == last tick", c.close == 101.0),
        ("Volume == sum", c.volume == sum(volumes)),
        ("Symbol correct", c.symbol == "RELIANCE"),
        ("Timeframe correct", c.timeframe == "1m"),
        ("is_complete", c.is_complete),
    ]

    all_pass = True
    for label, ok in checks:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {label}")
        if not ok:
            all_pass = False

    return all_pass


def verify_indicator_calculation():
    """Verify indicators are calculated correctly from candles."""
    print("\n" + "=" * 60)
    print("2. INDICATOR CALCULATION VERIFICATION")
    print("=" * 60)

    engine = IndicatorEngine()
    base = datetime(2025, 1, 6, 9, 15, 0)

    # Feed 110 candles (enough for all indicators)
    for i in range(110):
        price = 100.0 + (i % 10) * 0.5 - 2.5  # oscillating price
        candle = Candle(
            symbol="TCS", timeframe="1m",
            open=price - 0.2, high=price + 0.5,
            low=price - 0.5, close=price,
            volume=10000 + i * 100,
            timestamp=base + timedelta(minutes=i),
            is_complete=True,
        )
        result = engine.add_candle(candle)

    if result is None:
        print("  FAIL: No indicators returned after 110 candles")
        return False

    checks = [
        ("RSI in [0, 100]", 0 <= result.rsi_14 <= 100),
        ("BB upper > BB middle", result.bb_upper > result.bb_middle),
        ("BB middle > BB lower", result.bb_middle > result.bb_lower),
        ("EMA 9 > 0", result.ema_9 > 0),
        ("EMA 21 > 0", result.ema_21 > 0),
        ("ATR > 0", result.atr_14 > 0),
        ("VWAP > 0", result.vwap > 0),
        ("Supertrend > 0", result.supertrend > 0),
        ("Supertrend dir in {-1, 1}", result.supertrend_direction in (-1, 1)),
        ("Volume avg > 0", result.volume_avg_20 > 0),
        ("Symbol == TCS", result.symbol == "TCS"),
        ("Timeframe == 1m", result.timeframe == "1m"),
    ]

    all_pass = True
    for label, ok in checks:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {label}")
        if not ok:
            all_pass = False

    print(f"\n  Indicator snapshot:")
    print(f"    RSI(14)={result.rsi_14:.2f}  MACD={result.macd:.4f}")
    print(f"    BB: {result.bb_lower:.2f} / {result.bb_middle:.2f} / {result.bb_upper:.2f}")
    print(f"    EMA(9)={result.ema_9:.2f}  EMA(21)={result.ema_21:.2f}")
    print(f"    ATR(14)={result.atr_14:.4f}  VWAP={result.vwap:.2f}")
    print(f"    Supertrend={result.supertrend:.2f} dir={result.supertrend_direction}")

    return all_pass


def verify_mean_reversion_signal():
    """Verify Mean Reversion strategy generates signals when conditions are met."""
    print("\n" + "=" * 60)
    print("3. MEAN REVERSION SIGNAL GENERATION VERIFICATION")
    print("=" * 60)

    import pandas as pd

    config = MeanRevConfig(
        enabled=True, rsi_oversold=30, rsi_overbought=65,
        volume_multiplier=1.5, stop_loss_atr_multiplier=1.5,
    )
    strategy = MeanReversionStrategy(config)

    # Craft indicators that satisfy all 4 entry conditions
    indicators = IndicatorSet(
        symbol="INFY", timeframe="1m", timestamp=datetime.now(),
        rsi_14=25.0,        # < 30 (oversold)
        macd=0.5, macd_signal=0.3, macd_hist=0.2,
        bb_upper=110.0, bb_middle=105.0, bb_lower=100.5,  # price < bb_lower
        vwap=99.0,           # price > vwap
        ema_9=101.0, ema_21=102.0,
        supertrend=98.0, supertrend_direction=1,
        atr_14=2.0, volume_avg_20=5000.0,
    )

    candles_df = pd.DataFrame([{
        "open": 99.8, "high": 100.2, "low": 99.5,
        "close": 100.0,     # < bb_lower (100.5)
        "volume": 8000.0,   # > 1.5 * 5000 = 7500
        "timestamp": datetime.now(),
    }])

    signal = strategy.generate_signal(indicators, candles_df)

    checks = [
        ("Signal generated", signal is not None),
    ]

    if signal:
        expected_sl = 100.0 - (1.5 * 2.0)  # entry - 1.5*ATR = 97.0
        checks += [
            ("Side == BUY", signal.side == "BUY"),
            ("Strategy == MeanReversion", signal.strategy == "MeanReversion"),
            ("Entry price == 100.0", signal.entry_price == 100.0),
            ("Stop loss == 97.0", abs(signal.stop_loss - expected_sl) < 0.01),
            ("Target == BB middle (105.0)", signal.target == 105.0),
            ("Symbol == INFY", signal.symbol == "INFY"),
            ("Has signal_id", len(signal.signal_id) > 0),
        ]

    all_pass = True
    for label, ok in checks:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {label}")
        if not ok:
            all_pass = False

    # Verify NO signal when conditions not met (RSI too high)
    indicators_no_signal = IndicatorSet(
        symbol="INFY", timeframe="1m", timestamp=datetime.now(),
        rsi_14=55.0,  # > 30, not oversold
        macd=0.5, macd_signal=0.3, macd_hist=0.2,
        bb_upper=110.0, bb_middle=105.0, bb_lower=100.5,
        vwap=99.0, ema_9=101.0, ema_21=102.0,
        supertrend=98.0, supertrend_direction=1,
        atr_14=2.0, volume_avg_20=5000.0,
    )
    no_signal = strategy.generate_signal(indicators_no_signal, candles_df)
    ok = no_signal is None
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] No signal when RSI > oversold threshold")
    if not ok:
        all_pass = False

    return all_pass


def verify_strategy_status():
    """Report on the implementation status of all three strategies."""
    print("\n" + "=" * 60)
    print("4. STRATEGY IMPLEMENTATION STATUS")
    print("=" * 60)

    # Mean Reversion - implemented
    print("  [DONE] Mean Reversion strategy - fully implemented and tested")

    # Trend Following - queued (task 14.4)
    print("  [QUEUED] Trend Following strategy - task 14.4 (queued, not yet implemented)")

    # Opening Range Breakout - queued (task 14.6)
    print("  [QUEUED] Opening Range Breakout strategy - task 14.6 (queued, not yet implemented)")

    # Signal pipeline - queued (task 14.8)
    print("  [QUEUED] Signal generation pipeline - task 14.8 (queued)")

    # Trading hours filter - queued (task 14.10)
    print("  [QUEUED] Trading hours signal filter - task 14.10 (queued)")

    # Duplicate position prevention - queued (task 14.11)
    print("  [QUEUED] Duplicate position prevention - task 14.11 (queued)")


def verify_end_to_end_pipeline():
    """Verify the full tick → candle → indicator pipeline works end-to-end."""
    print("\n" + "=" * 60)
    print("5. END-TO-END PIPELINE VERIFICATION (tick → candle → indicator)")
    print("=" * 60)

    engine = IndicatorEngine()
    builder = CandleBuilder(timeframes=["1m"])

    completed_candles = []
    indicator_results = []

    def on_candle(candle):
        completed_candles.append(candle)
        result = engine.add_candle(candle)
        if result:
            indicator_results.append(result)

    builder.on_candle_complete(on_candle)

    base = datetime(2025, 1, 6, 9, 15, 0)

    # Feed 120 minutes of ticks (2 hours), 1 tick per second
    # This should produce ~120 candles
    for minute in range(120):
        price = 500.0 + (minute % 20) * 2.0 - 20.0
        for sec in range(0, 60, 15):  # 4 ticks per minute
            ts = base + timedelta(minutes=minute, seconds=sec)
            tick = make_tick("HDFCBANK", price + sec * 0.01, 5000 + sec * 10, ts)
            builder.process_tick(tick)

    builder.flush()

    checks = [
        ("Candles produced", len(completed_candles) > 100),
        ("Indicators produced", len(indicator_results) > 0),
    ]

    if indicator_results:
        last = indicator_results[-1]
        checks += [
            ("Last indicator has valid RSI", 0 <= last.rsi_14 <= 100),
            ("Last indicator has valid ATR", last.atr_14 > 0),
            ("Last indicator symbol == HDFCBANK", last.symbol == "HDFCBANK"),
        ]

    all_pass = True
    for label, ok in checks:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {label}")
        if not ok:
            all_pass = False

    print(f"\n  Pipeline stats:")
    print(f"    Candles produced: {len(completed_candles)}")
    print(f"    Indicators produced: {len(indicator_results)}")
    if indicator_results:
        first_idx = completed_candles.index(completed_candles[0])
        print(f"    First indicator after candle #{len(completed_candles) - len(indicator_results) + 1}")

    return all_pass


def main():
    print("\n" + "#" * 60)
    print("  CHECKPOINT 15: Technical Analysis Pipeline Verification")
    print("#" * 60)

    results = {}
    results["Candle Building"] = verify_candle_building()
    results["Indicator Calculation"] = verify_indicator_calculation()
    results["Mean Reversion Signal"] = verify_mean_reversion_signal()
    verify_strategy_status()
    results["End-to-End Pipeline"] = verify_end_to_end_pipeline()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    all_pass = True
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")
        if not passed:
            all_pass = False

    print("\n  Note: Trend Following (14.4), ORB (14.6), signal pipeline (14.8),")
    print("  trading hours filter (14.10), and duplicate prevention (14.11)")
    print("  are queued tasks — not yet implemented.")

    if all_pass:
        print("\n  All implemented components verified successfully.")
    else:
        print("\n  Some checks FAILED — see details above.")

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
