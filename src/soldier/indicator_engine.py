"""
Indicator Engine for LOHI-TRADE.

Calculates technical indicators on completed candles using pandas-ta.
Maintains a rolling window of the last 100 candles per (symbol, timeframe)
and computes RSI, MACD, Bollinger Bands, VWAP, EMA, Supertrend, and ATR
in a single pass.

Requirements: 3.1, 3.2, 3.3, 3.4, 3.6
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

try:
    import pandas_ta as ta
    HAS_PANDAS_TA = True
except ImportError:
    HAS_PANDAS_TA = False
    ta = None

from src.soldier.candle_builder import Candle
from src.utils.logger import get_logger

logger = get_logger("IndicatorEngine")

# Maximum number of candles to keep per (symbol, timeframe)
MAX_ROLLING_WINDOW = 100

# Minimum candles required for indicator calculation.
# MACD needs 26 (slow period) + 9 (signal) = 35 warm-up rows,
# but pandas-ta handles warm-up internally. We need at least 26
# candles so the MACD slow EMA has enough data, plus some buffer.
MIN_CANDLES_REQUIRED = 35


@dataclass
class IndicatorSet:
    """
    Complete set of technical indicators for a symbol at a point in time.

    Attributes:
        symbol: Trading symbol (e.g., "RELIANCE")
        timeframe: Candle timeframe (e.g., "1m", "5m", "15m")
        timestamp: Timestamp of the candle these indicators were calculated from
        rsi_14: Relative Strength Index (14-period)
        macd: MACD line value
        macd_signal: MACD signal line value
        macd_hist: MACD histogram value
        bb_upper: Bollinger Band upper (20, 2)
        bb_middle: Bollinger Band middle (20-period SMA)
        bb_lower: Bollinger Band lower (20, 2)
        vwap: Volume Weighted Average Price
        ema_9: Exponential Moving Average (9-period)
        ema_21: Exponential Moving Average (21-period)
        supertrend: Supertrend value (7, 3)
        supertrend_direction: Supertrend direction (1=bullish, -1=bearish)
        atr_14: Average True Range (14-period)
        volume_avg_20: 20-period volume moving average
    """

    symbol: str
    timeframe: str
    timestamp: datetime
    rsi_14: float
    macd: float
    macd_signal: float
    macd_hist: float
    bb_upper: float
    bb_middle: float
    bb_lower: float
    vwap: float
    ema_9: float
    ema_21: float
    supertrend: float
    supertrend_direction: int
    atr_14: float
    volume_avg_20: float
    # Extended TA indicators
    stoch_k: float = 50.0          # Stochastic %K (14, 3, 3)
    stoch_d: float = 50.0          # Stochastic %D
    adx: float = 25.0              # Average Directional Index (14)
    plus_di: float = 0.0           # +DI (14)
    minus_di: float = 0.0          # -DI (14)
    williams_r: float = -50.0      # Williams %R (14)
    cci: float = 0.0               # Commodity Channel Index (20)
    obv: float = 0.0               # On-Balance Volume
    mfi: float = 50.0              # Money Flow Index (14)
    psar: float = 0.0              # Parabolic SAR
    psar_direction: int = 1        # 1=bullish (price above SAR), -1=bearish
    ema_50: float = 0.0            # EMA 50 for longer-term trend
    ema_200: float = 0.0           # EMA 200 for major trend
    pivot: float = 0.0             # Daily pivot point
    pivot_r1: float = 0.0          # Resistance 1
    pivot_s1: float = 0.0          # Support 1
    ichimoku_tenkan: float = 0.0   # Tenkan-sen (conversion line, 9)
    ichimoku_kijun: float = 0.0    # Kijun-sen (base line, 26)
    ichimoku_senkou_a: float = 0.0 # Senkou Span A (leading span A)
    ichimoku_senkou_b: float = 0.0 # Senkou Span B (leading span B)
    rsi_9: float = 50.0            # RSI short period for divergence detection
    sma_20: float = 0.0            # SMA 20 (BB middle equivalent)
    volume_ratio: float = 1.0      # Current volume / avg volume


class IndicatorEngine:
    """
    Calculates technical indicators on completed candles.

    Maintains a rolling window of the last 100 candles per (symbol, timeframe)
    pair and recalculates all indicators when a new candle is added.

    Requirements: 3.1, 3.2, 3.4
    """

    def __init__(self) -> None:
        self._candle_windows: Dict[Tuple[str, str], list[Candle]] = defaultdict(list)
        self._latest_indicators: Dict[Tuple[str, str], IndicatorSet] = {}

    def add_candle(self, candle: Candle) -> Optional[IndicatorSet]:
        """
        Add a completed candle and recalculate indicators.

        Appends the candle to the rolling window for its (symbol, timeframe),
        trims to MAX_ROLLING_WINDOW, and calculates all indicators.

        Args:
            candle: A completed Candle object.

        Returns:
            IndicatorSet if calculation succeeds, None if insufficient data
            or calculation error.

        Requirements: 3.1, 3.3, 3.6
        """
        key = (candle.symbol, candle.timeframe)

        # Append and trim to rolling window
        self._candle_windows[key].append(candle)
        if len(self._candle_windows[key]) > MAX_ROLLING_WINDOW:
            self._candle_windows[key] = self._candle_windows[key][-MAX_ROLLING_WINDOW:]

        # Check minimum data requirement
        if len(self._candle_windows[key]) < MIN_CANDLES_REQUIRED:
            logger.debug(
                f"Insufficient data for {candle.symbol}/{candle.timeframe}: "
                f"{len(self._candle_windows[key])}/{MIN_CANDLES_REQUIRED} candles"
            )
            return None

        try:
            df = self._candles_to_dataframe(self._candle_windows[key])
            result = self.calculate_indicators(df, candle.symbol, candle.timeframe)
            if result is not None:
                self._latest_indicators[key] = result
            return result
        except Exception as e:
            logger.error(
                f"Indicator calculation failed for {candle.symbol}/{candle.timeframe}: {e}",
                exc_info=True,
            )
            return None

    def calculate_indicators(
        self, df: pd.DataFrame, symbol: str, timeframe: str
    ) -> Optional[IndicatorSet]:
        """
        Calculate all technical indicators from a candle DataFrame.

        Args:
            df: DataFrame with columns: open, high, low, close, volume, timestamp.
            symbol: Trading symbol.
            timeframe: Candle timeframe.

        Returns:
            IndicatorSet with all calculated indicators, or None if any
            core indicator produces NaN.

        Requirements: 3.1, 3.2
        """
        if not HAS_PANDAS_TA:
            logger.warning(
                "pandas-ta not installed; indicators will not be calculated. "
                "Install with: pip install lohi-trade[ml]"
            )
            return None
        
        try:
            # RSI (14)
            rsi = ta.rsi(df["close"], length=14)

            # MACD (12, 26, 9)
            macd_df = ta.macd(df["close"], fast=12, slow=26, signal=9)
            if macd_df is None:
                logger.debug(
                    f"MACD returned None for {symbol}/{timeframe}, "
                    f"insufficient warm-up data ({len(df)} candles)"
                )
                return None

            # Bollinger Bands (20, 2)
            bb_df = ta.bbands(df["close"], length=20, std=2)

            # EMA (9, 21)
            ema_9 = ta.ema(df["close"], length=9)
            ema_21 = ta.ema(df["close"], length=21)

            # ATR (14)
            atr = ta.atr(df["high"], df["low"], df["close"], length=14)

            # Supertrend (7, 3)
            st_df = ta.supertrend(df["high"], df["low"], df["close"], length=7, multiplier=3)

            # Volume average (20)
            volume_avg = ta.sma(df["volume"].astype(float), length=20)

            # VWAP - cumulative (typical_price * volume) / cumulative volume
            vwap = self._calculate_vwap(df)

            # --- Extended TA indicators ---
            # Stochastic Oscillator (14, 3, 3)
            stoch_df = ta.stoch(df["high"], df["low"], df["close"], k=14, d=3, smooth_k=3)

            # ADX / +DI / -DI (14)
            adx_df = ta.adx(df["high"], df["low"], df["close"], length=14)

            # Williams %R (14)
            willr = ta.willr(df["high"], df["low"], df["close"], length=14)

            # CCI (20)
            cci = ta.cci(df["high"], df["low"], df["close"], length=20)

            # OBV
            obv = ta.obv(df["close"], df["volume"])

            # MFI (14)
            mfi = ta.mfi(df["high"], df["low"], df["close"], df["volume"], length=14)

            # Parabolic SAR
            psar_df = ta.psar(df["high"], df["low"], df["close"])

            # EMA 50, 200
            ema_50 = ta.ema(df["close"], length=50)
            ema_200 = ta.ema(df["close"], length=min(len(df), 200))

            # RSI short (9)
            rsi_9 = ta.rsi(df["close"], length=9)

            # SMA 20
            sma_20 = ta.sma(df["close"], length=20)

            # Ichimoku (9, 26, 52)
            ichimoku_df, _ = ta.ichimoku(df["high"], df["low"], df["close"],
                                          tenkan=9, kijun=26, senkou=52)

            # Extract latest values
            idx = len(df) - 1

            rsi_val = rsi.iloc[idx]
            macd_val = macd_df.iloc[idx, 0]  # MACD line
            macd_signal_val = macd_df.iloc[idx, 1]  # Signal line
            macd_hist_val = macd_df.iloc[idx, 2]  # Histogram
            bb_lower_val = bb_df.iloc[idx, 0]  # BBL
            bb_middle_val = bb_df.iloc[idx, 1]  # BBM
            bb_upper_val = bb_df.iloc[idx, 2]  # BBU
            ema_9_val = ema_9.iloc[idx]
            ema_21_val = ema_21.iloc[idx]
            atr_val = atr.iloc[idx]
            volume_avg_val = volume_avg.iloc[idx]
            vwap_val = vwap.iloc[idx]

            # Supertrend columns: SUPERT_7_3.0, SUPERTd_7_3.0, SUPERTl_7_3.0, SUPERTs_7_3.0
            st_cols = st_df.columns
            supertrend_val = st_df[st_cols[0]].iloc[idx]  # SUPERT value
            supertrend_dir_val = st_df[st_cols[1]].iloc[idx]  # SUPERTd direction

            # Extended indicator extraction
            stoch_k_val = stoch_df.iloc[idx, 0] if stoch_df is not None else 50.0
            stoch_d_val = stoch_df.iloc[idx, 1] if stoch_df is not None else 50.0
            adx_val = adx_df.iloc[idx, 0] if adx_df is not None else 25.0
            plus_di_val = adx_df.iloc[idx, 1] if adx_df is not None else 0.0
            minus_di_val = adx_df.iloc[idx, 2] if adx_df is not None else 0.0
            willr_val = willr.iloc[idx] if willr is not None else -50.0
            cci_val = cci.iloc[idx] if cci is not None else 0.0
            obv_val = obv.iloc[idx] if obv is not None else 0.0
            mfi_val = mfi.iloc[idx] if mfi is not None else 50.0
            rsi_9_val = rsi_9.iloc[idx] if rsi_9 is not None else 50.0
            sma_20_val = sma_20.iloc[idx] if sma_20 is not None else df["close"].iloc[idx]
            ema_50_val = ema_50.iloc[idx] if ema_50 is not None else df["close"].iloc[idx]
            ema_200_val = ema_200.iloc[idx] if ema_200 is not None else df["close"].iloc[idx]

            # Parabolic SAR extraction
            if psar_df is not None:
                psar_cols = psar_df.columns
                # PSARl = long SAR (bullish), PSARs = short SAR (bearish)
                psar_long = psar_df[psar_cols[0]].iloc[idx]
                psar_short = psar_df[psar_cols[1]].iloc[idx]
                if not pd.isna(psar_long):
                    psar_val = float(psar_long)
                    psar_dir_val = 1  # bullish
                elif not pd.isna(psar_short):
                    psar_val = float(psar_short)
                    psar_dir_val = -1  # bearish
                else:
                    psar_val = df["close"].iloc[idx]
                    psar_dir_val = 1
            else:
                psar_val = df["close"].iloc[idx]
                psar_dir_val = 1

            # Ichimoku extraction
            if ichimoku_df is not None and not ichimoku_df.empty:
                ichi_cols = ichimoku_df.columns
                tenkan_val = ichimoku_df[ichi_cols[0]].iloc[idx] if len(ichi_cols) > 0 else 0.0
                kijun_val = ichimoku_df[ichi_cols[1]].iloc[idx] if len(ichi_cols) > 1 else 0.0
                senkou_a_val = ichimoku_df[ichi_cols[2]].iloc[idx] if len(ichi_cols) > 2 else 0.0
                senkou_b_val = ichimoku_df[ichi_cols[3]].iloc[idx] if len(ichi_cols) > 3 else 0.0
            else:
                tenkan_val = kijun_val = senkou_a_val = senkou_b_val = df["close"].iloc[idx]

            # Pivot Points (classic: based on previous candle's HLC)
            if len(df) >= 2:
                prev = df.iloc[-2]
                pivot_val = (float(prev["high"]) + float(prev["low"]) + float(prev["close"])) / 3
                pivot_r1_val = 2 * pivot_val - float(prev["low"])
                pivot_s1_val = 2 * pivot_val - float(prev["high"])
            else:
                close_val = float(df["close"].iloc[idx])
                pivot_val = pivot_r1_val = pivot_s1_val = close_val

            # Volume ratio
            vol_ratio_val = (float(df["volume"].iloc[idx]) / float(volume_avg_val)
                             if volume_avg_val and not pd.isna(volume_avg_val) and volume_avg_val > 0
                             else 1.0)

            # Check for NaN in core indicators
            core_values = [
                rsi_val, macd_val, macd_signal_val, macd_hist_val,
                bb_upper_val, bb_middle_val, bb_lower_val,
                ema_9_val, ema_21_val, atr_val, supertrend_val,
            ]
            if any(pd.isna(v) for v in core_values):
                logger.debug(
                    f"NaN detected in core indicators for {symbol}/{timeframe}, "
                    f"likely insufficient warm-up data"
                )
                return None

            # Handle NaN in non-critical indicators with sensible defaults
            if pd.isna(vwap_val):
                vwap_val = df["close"].iloc[idx]
            if pd.isna(volume_avg_val):
                volume_avg_val = df["volume"].astype(float).mean()
            if pd.isna(supertrend_dir_val):
                supertrend_dir_val = 1

            # Clamp extended NaN values
            def _safe(v, default=0.0):
                return default if pd.isna(v) else float(v)

            return IndicatorSet(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=df["timestamp"].iloc[idx],
                rsi_14=float(rsi_val),
                macd=float(macd_val),
                macd_signal=float(macd_signal_val),
                macd_hist=float(macd_hist_val),
                bb_upper=float(bb_upper_val),
                bb_middle=float(bb_middle_val),
                bb_lower=float(bb_lower_val),
                vwap=float(vwap_val),
                ema_9=float(ema_9_val),
                ema_21=float(ema_21_val),
                supertrend=float(supertrend_val),
                supertrend_direction=int(supertrend_dir_val),
                atr_14=float(atr_val),
                volume_avg_20=float(volume_avg_val),
                stoch_k=_safe(stoch_k_val, 50.0),
                stoch_d=_safe(stoch_d_val, 50.0),
                adx=_safe(adx_val, 25.0),
                plus_di=_safe(plus_di_val),
                minus_di=_safe(minus_di_val),
                williams_r=_safe(willr_val, -50.0),
                cci=_safe(cci_val),
                obv=_safe(obv_val),
                mfi=_safe(mfi_val, 50.0),
                psar=_safe(psar_val),
                psar_direction=int(psar_dir_val),
                ema_50=_safe(ema_50_val),
                ema_200=_safe(ema_200_val),
                pivot=_safe(pivot_val),
                pivot_r1=_safe(pivot_r1_val),
                pivot_s1=_safe(pivot_s1_val),
                ichimoku_tenkan=_safe(tenkan_val),
                ichimoku_kijun=_safe(kijun_val),
                ichimoku_senkou_a=_safe(senkou_a_val),
                ichimoku_senkou_b=_safe(senkou_b_val),
                rsi_9=_safe(rsi_9_val, 50.0),
                sma_20=_safe(sma_20_val),
                volume_ratio=_safe(vol_ratio_val, 1.0),
            )

        except Exception as e:
            logger.error(
                f"Error calculating indicators for {symbol}/{timeframe}: {e}",
                exc_info=True,
            )
            return None

    def get_latest_indicators(self, symbol: str, timeframe: str = "1m") -> Optional[IndicatorSet]:
        """
        Get the most recently calculated indicators for a symbol.

        Args:
            symbol: Trading symbol.
            timeframe: Candle timeframe (default "1m").

        Returns:
            The latest IndicatorSet, or None if not yet calculated.
        """
        return self._latest_indicators.get((symbol, timeframe))

    def get_candle_count(self, symbol: str, timeframe: str = "1m") -> int:
        """
        Get the number of candles in the rolling window for a symbol.

        Args:
            symbol: Trading symbol.
            timeframe: Candle timeframe.

        Returns:
            Number of candles currently stored.
        """
        return len(self._candle_windows.get((symbol, timeframe), []))

    def reset(self, symbol: Optional[str] = None, timeframe: Optional[str] = None) -> None:
        """
        Reset candle windows and cached indicators.

        Args:
            symbol: If provided with timeframe, reset only that pair.
                    If None, reset everything.
            timeframe: Timeframe to reset (used with symbol).
        """
        if symbol is not None and timeframe is not None:
            key = (symbol, timeframe)
            self._candle_windows.pop(key, None)
            self._latest_indicators.pop(key, None)
        else:
            self._candle_windows.clear()
            self._latest_indicators.clear()

    @staticmethod
    def _candles_to_dataframe(candles: list[Candle]) -> pd.DataFrame:
        """Convert a list of Candle objects to a pandas DataFrame."""
        data = {
            "open": [c.open for c in candles],
            "high": [c.high for c in candles],
            "low": [c.low for c in candles],
            "close": [c.close for c in candles],
            "volume": [c.volume for c in candles],
            "timestamp": [c.timestamp for c in candles],
        }
        return pd.DataFrame(data)

    @staticmethod
    def _calculate_vwap(df: pd.DataFrame) -> pd.Series:
        """
        Calculate VWAP as cumulative (typical_price * volume) / cumulative volume.

        Uses the standard typical price = (high + low + close) / 3.
        """
        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        cum_tp_vol = (typical_price * df["volume"]).cumsum()
        cum_vol = df["volume"].cumsum()
        # Avoid division by zero
        vwap = cum_tp_vol / cum_vol.replace(0, np.nan)
        return vwap
