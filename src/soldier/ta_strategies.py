"""Extended Technical Analysis Strategies for LOHI-TRADE.

Implements 10 additional strategies derived from classical TA workbook patterns:
1. VWAP Bounce — Institutional support/resistance at VWAP
2. Stochastic RSI Combo — Dual oscillator oversold/overbought
3. ADX Trend Strength — Strong trend entry with DI crossover
4. Bollinger Squeeze — Volatility contraction breakout
5. Pivot Point — Support/resistance bounce/breakout
6. Ichimoku Cloud — Full cloud-based trend system
7. MACD Divergence — Price/momentum divergence reversal
8. Parabolic SAR Trend — SAR + EMA trend continuation
9. Volume Breakout — Volume-confirmed price breakout
10. Multi-Timeframe Momentum — Confluence of multiple indicators

All strategies follow the Strategy ABC interface and produce Signal objects
compatible with the existing SignalPipeline and ML filter.
"""

import pandas as pd

from src.soldier.indicator_engine import IndicatorSet
from src.soldier.strategy_engine import Signal, Strategy, create_signal
from src.utils.config import (
    ADXTrendStrategy as ADXTrendConfig,
)
from src.utils.config import (
    BollingerSqueezeStrategy as BollingerSqueezeConfig,
)
from src.utils.config import (
    IchimokuCloudStrategy as IchimokuCloudConfig,
)
from src.utils.config import (
    MACDDivergenceStrategy as MACDDivergenceConfig,
)
from src.utils.config import (
    MultiTimeframeMomentumStrategy as MTFMomentumConfig,
)
from src.utils.config import (
    ParabolicSARTrendStrategy as ParabolicSARConfig,
)
from src.utils.config import (
    PivotPointStrategy as PivotPointConfig,
)
from src.utils.config import (
    StochasticRSIStrategy as StochRSIConfig,
)
from src.utils.config import (
    VolumeBreakoutStrategy as VolumeBreakoutConfig,
)
from src.utils.config import (
    VWAPBounceStrategy as VWAPBounceConfig,
)
from src.utils.logger import get_logger

logger = get_logger("TAStrategies")


# ---------------------------------------------------------------------------
# 1. VWAP Bounce Strategy
# ---------------------------------------------------------------------------
class VWAPBounceStrategyImpl(Strategy):
    """VWAP Bounce: enters when price pulls back to VWAP and bounces with
    volume confirmation. VWAP acts as dynamic institutional support/resistance.

    BUY: price within vwap_proximity_pct of VWAP, RSI neutral (40-60),
         volume above average, price bouncing up (close > open on last candle).
    SELL: mirror conditions for short.
    """

    def __init__(self, config: VWAPBounceConfig) -> None:
        self._config = config

    @property
    def name(self) -> str:
        return "VWAPBounce"

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    def generate_signal(
        self,
        indicators: IndicatorSet,
        candles: pd.DataFrame,
    ) -> Signal | None:
        if not self._config.enabled or candles.empty:
            return None

        last = candles.iloc[-1]
        close = float(last["close"])
        open_price = float(last["open"])
        volume = float(last["volume"])

        # Price must be near VWAP
        vwap_dist_pct = abs(close - indicators.vwap) / indicators.vwap * 100
        if vwap_dist_pct > self._config.vwap_proximity_pct:
            return None

        # RSI in neutral zone (not overbought/oversold — waiting for bounce)
        if not (self._config.rsi_min <= indicators.rsi_14 <= self._config.rsi_max):
            return None

        # Volume confirmation
        if volume < self._config.volume_multiplier * indicators.volume_avg_20:
            return None

        # Determine direction from candle body
        if close > open_price and close >= indicators.vwap:
            side = "BUY"
            stop_loss = close - self._config.stop_loss_atr_multiplier * indicators.atr_14
            target = close + self._config.target_atr_multiplier * indicators.atr_14
        elif close < open_price and close <= indicators.vwap:
            side = "SELL"
            stop_loss = close + self._config.stop_loss_atr_multiplier * indicators.atr_14
            target = close - self._config.target_atr_multiplier * indicators.atr_14
        else:
            return None

        logger.info(
            f"VWAPBounce signal: {indicators.symbol} {side} "
            f"entry={close:.2f} vwap={indicators.vwap:.2f}",
        )
        return create_signal(
            symbol=indicators.symbol,
            strategy=self.name,
            side=side,
            entry_price=close,
            stop_loss=stop_loss,
            target=target,
            indicators=indicators,
        )


# ---------------------------------------------------------------------------
# 2. Stochastic + RSI Combo Strategy
# ---------------------------------------------------------------------------
class StochasticRSIStrategyImpl(Strategy):
    """Dual oscillator strategy: enters when both Stochastic and RSI agree
    on oversold (BUY) or overbought (SELL) conditions.

    BUY: Stoch %K < oversold AND RSI < oversold AND %K crosses above %D.
    SELL: Stoch %K > overbought AND RSI > overbought AND %K crosses below %D.
    """

    def __init__(self, config: StochRSIConfig) -> None:
        self._config = config

    @property
    def name(self) -> str:
        return "StochasticRSI"

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    def generate_signal(
        self,
        indicators: IndicatorSet,
        candles: pd.DataFrame,
    ) -> Signal | None:
        if not self._config.enabled or candles.empty:
            return None

        close = float(candles.iloc[-1]["close"])
        stoch_k = indicators.stoch_k
        stoch_d = indicators.stoch_d
        rsi = indicators.rsi_14

        side = None
        if (
            stoch_k < self._config.stoch_oversold
            and rsi < self._config.rsi_oversold
            and stoch_k > stoch_d
        ):  # %K crossing above %D
            side = "BUY"
        elif (
            stoch_k > self._config.stoch_overbought
            and rsi > self._config.rsi_overbought
            and stoch_k < stoch_d
        ):  # %K crossing below %D
            side = "SELL"

        if side is None:
            return None

        if side == "BUY":
            stop_loss = close - self._config.stop_loss_atr_multiplier * indicators.atr_14
            target = close + self._config.target_atr_multiplier * indicators.atr_14
        else:
            stop_loss = close + self._config.stop_loss_atr_multiplier * indicators.atr_14
            target = close - self._config.target_atr_multiplier * indicators.atr_14

        logger.info(
            f"StochasticRSI signal: {indicators.symbol} {side} "
            f"StochK={stoch_k:.1f} RSI={rsi:.1f}",
        )
        return create_signal(
            symbol=indicators.symbol,
            strategy=self.name,
            side=side,
            entry_price=close,
            stop_loss=stop_loss,
            target=target,
            indicators=indicators,
        )


# ---------------------------------------------------------------------------
# 3. ADX Trend Strength Strategy
# ---------------------------------------------------------------------------
class ADXTrendStrategyImpl(Strategy):
    """ADX-based trend entry: only trades when ADX confirms a strong trend
    (ADX > threshold) and +DI/-DI crossover indicates direction.

    BUY: ADX > threshold AND +DI > -DI AND price > VWAP.
    SELL: ADX > threshold AND -DI > +DI AND price < VWAP.
    """

    def __init__(self, config: ADXTrendConfig) -> None:
        self._config = config

    @property
    def name(self) -> str:
        return "ADXTrend"

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    def generate_signal(
        self,
        indicators: IndicatorSet,
        candles: pd.DataFrame,
    ) -> Signal | None:
        if not self._config.enabled or candles.empty:
            return None

        close = float(candles.iloc[-1]["close"])
        volume = float(candles.iloc[-1]["volume"])

        # ADX must show strong trend
        if indicators.adx < self._config.adx_threshold:
            return None

        # Volume filter
        if volume < self._config.volume_multiplier * indicators.volume_avg_20:
            return None

        side = None
        if indicators.plus_di > indicators.minus_di and close > indicators.vwap:
            side = "BUY"
        elif indicators.minus_di > indicators.plus_di and close < indicators.vwap:
            side = "SELL"

        if side is None:
            return None

        if side == "BUY":
            stop_loss = close - self._config.stop_loss_atr_multiplier * indicators.atr_14
            target = close + self._config.target_atr_multiplier * indicators.atr_14
        else:
            stop_loss = close + self._config.stop_loss_atr_multiplier * indicators.atr_14
            target = close - self._config.target_atr_multiplier * indicators.atr_14

        logger.info(
            f"ADXTrend signal: {indicators.symbol} {side} "
            f"ADX={indicators.adx:.1f} +DI={indicators.plus_di:.1f} -DI={indicators.minus_di:.1f}",
        )
        return create_signal(
            symbol=indicators.symbol,
            strategy=self.name,
            side=side,
            entry_price=close,
            stop_loss=stop_loss,
            target=target,
            indicators=indicators,
        )


# ---------------------------------------------------------------------------
# 4. Bollinger Band Squeeze Strategy
# ---------------------------------------------------------------------------
class BollingerSqueezeStrategyImpl(Strategy):
    """Bollinger Squeeze: detects low-volatility compression (narrow bands)
    and enters on the breakout direction with volume confirmation.

    The squeeze is identified when BB width falls below a threshold.
    Entry triggers when price breaks out of the bands with volume spike.

    BUY: BB width < threshold AND close > BB upper AND volume spike.
    SELL: BB width < threshold AND close < BB lower AND volume spike.
    """

    def __init__(self, config: BollingerSqueezeConfig) -> None:
        self._config = config

    @property
    def name(self) -> str:
        return "BollingerSqueeze"

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    def generate_signal(
        self,
        indicators: IndicatorSet,
        candles: pd.DataFrame,
    ) -> Signal | None:
        if not self._config.enabled or candles.empty:
            return None

        close = float(candles.iloc[-1]["close"])
        volume = float(candles.iloc[-1]["volume"])

        # Calculate BB width as percentage
        bb_width = (
            (indicators.bb_upper - indicators.bb_lower) / indicators.bb_middle
            if indicators.bb_middle > 0
            else 999
        )

        # Check for squeeze condition (narrow bands)
        if bb_width > self._config.squeeze_bb_width_threshold:
            return None

        # Volume must confirm breakout
        if volume < self._config.breakout_volume_multiplier * indicators.volume_avg_20:
            return None

        side = None
        if close > indicators.bb_upper:
            side = "BUY"
        elif close < indicators.bb_lower:
            side = "SELL"

        if side is None:
            return None

        if side == "BUY":
            stop_loss = close - self._config.stop_loss_atr_multiplier * indicators.atr_14
            target = close + self._config.target_atr_multiplier * indicators.atr_14
        else:
            stop_loss = close + self._config.stop_loss_atr_multiplier * indicators.atr_14
            target = close - self._config.target_atr_multiplier * indicators.atr_14

        logger.info(
            f"BollingerSqueeze signal: {indicators.symbol} {side} "
            f"bb_width={bb_width:.4f} close={close:.2f}",
        )
        return create_signal(
            symbol=indicators.symbol,
            strategy=self.name,
            side=side,
            entry_price=close,
            stop_loss=stop_loss,
            target=target,
            indicators=indicators,
        )


# ---------------------------------------------------------------------------
# 5. Pivot Point Strategy
# ---------------------------------------------------------------------------
class PivotPointStrategyImpl(Strategy):
    """Classic Pivot Point strategy: trades bounces off pivot support/resistance.

    BUY: price near S1 (within proximity_pct) AND RSI < 40 AND bouncing up.
    SELL: price near R1 (within proximity_pct) AND RSI > 60 AND rejecting down.
    """

    def __init__(self, config: PivotPointConfig) -> None:
        self._config = config

    @property
    def name(self) -> str:
        return "PivotPoint"

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    def generate_signal(
        self,
        indicators: IndicatorSet,
        candles: pd.DataFrame,
    ) -> Signal | None:
        if not self._config.enabled or candles.empty:
            return None

        last = candles.iloc[-1]
        close = float(last["close"])
        open_price = float(last["open"])
        volume = float(last["volume"])

        if volume < self._config.volume_multiplier * indicators.volume_avg_20:
            return None

        # Check proximity to S1 for BUY
        s1_dist_pct = (
            abs(close - indicators.pivot_s1) / indicators.pivot_s1 * 100
            if indicators.pivot_s1 > 0
            else 999
        )
        r1_dist_pct = (
            abs(close - indicators.pivot_r1) / indicators.pivot_r1 * 100
            if indicators.pivot_r1 > 0
            else 999
        )

        side = None
        if (
            s1_dist_pct < self._config.proximity_pct
            and close > open_price
            and indicators.rsi_14 < 40
        ):
            side = "BUY"
        elif (
            r1_dist_pct < self._config.proximity_pct
            and close < open_price
            and indicators.rsi_14 > 60
        ):
            side = "SELL"

        if side is None:
            return None

        if side == "BUY":
            stop_loss = close - self._config.stop_loss_atr_multiplier * indicators.atr_14
            target = indicators.pivot  # Target the pivot
        else:
            stop_loss = close + self._config.stop_loss_atr_multiplier * indicators.atr_14
            target = indicators.pivot

        logger.info(
            f"PivotPoint signal: {indicators.symbol} {side} "
            f"pivot={indicators.pivot:.2f} S1={indicators.pivot_s1:.2f} R1={indicators.pivot_r1:.2f}",
        )
        return create_signal(
            symbol=indicators.symbol,
            strategy=self.name,
            side=side,
            entry_price=close,
            stop_loss=stop_loss,
            target=target,
            indicators=indicators,
        )


# ---------------------------------------------------------------------------
# 6. Ichimoku Cloud Strategy
# ---------------------------------------------------------------------------
class IchimokuCloudStrategyImpl(Strategy):
    """Ichimoku Cloud: full cloud-based trend system.

    BUY: price > Senkou Span A AND price > Senkou Span B (above cloud)
         AND Tenkan > Kijun (TK cross bullish)
         AND close > VWAP.
    SELL: price < both Senkou spans (below cloud)
          AND Tenkan < Kijun AND close < VWAP.
    """

    def __init__(self, config: IchimokuCloudConfig) -> None:
        self._config = config

    @property
    def name(self) -> str:
        return "IchimokuCloud"

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    def generate_signal(
        self,
        indicators: IndicatorSet,
        candles: pd.DataFrame,
    ) -> Signal | None:
        if not self._config.enabled or candles.empty:
            return None

        close = float(candles.iloc[-1]["close"])
        cloud_top = max(indicators.ichimoku_senkou_a, indicators.ichimoku_senkou_b)
        cloud_bottom = min(indicators.ichimoku_senkou_a, indicators.ichimoku_senkou_b)

        side = None
        if (
            close > cloud_top
            and indicators.ichimoku_tenkan > indicators.ichimoku_kijun
            and close > indicators.vwap
        ):
            side = "BUY"
        elif (
            close < cloud_bottom
            and indicators.ichimoku_tenkan < indicators.ichimoku_kijun
            and close < indicators.vwap
        ):
            side = "SELL"

        if side is None:
            return None

        if side == "BUY":
            stop_loss = close - self._config.stop_loss_atr_multiplier * indicators.atr_14
            target = close + self._config.target_atr_multiplier * indicators.atr_14
        else:
            stop_loss = close + self._config.stop_loss_atr_multiplier * indicators.atr_14
            target = close - self._config.target_atr_multiplier * indicators.atr_14

        logger.info(
            f"IchimokuCloud signal: {indicators.symbol} {side} "
            f"tenkan={indicators.ichimoku_tenkan:.2f} kijun={indicators.ichimoku_kijun:.2f}",
        )
        return create_signal(
            symbol=indicators.symbol,
            strategy=self.name,
            side=side,
            entry_price=close,
            stop_loss=stop_loss,
            target=target,
            indicators=indicators,
        )


# ---------------------------------------------------------------------------
# 7. MACD Divergence Strategy
# ---------------------------------------------------------------------------
class MACDDivergenceStrategyImpl(Strategy):
    """MACD Divergence: detects bullish/bearish divergence between price
    and MACD histogram over a lookback window.

    Bullish divergence: price makes lower low but MACD hist makes higher low → BUY.
    Bearish divergence: price makes higher high but MACD hist makes lower high → SELL.
    """

    def __init__(self, config: MACDDivergenceConfig) -> None:
        self._config = config

    @property
    def name(self) -> str:
        return "MACDDivergence"

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    def generate_signal(
        self,
        indicators: IndicatorSet,
        candles: pd.DataFrame,
    ) -> Signal | None:
        if not self._config.enabled or candles.empty:
            return None

        lookback = self._config.lookback_candles
        if len(candles) < lookback + 1:
            return None

        recent = candles.iloc[-lookback:]
        close = float(candles.iloc[-1]["close"])

        # Find price lows/highs and compare with MACD histogram trend
        price_lows = recent["low"].values
        price_highs = recent["high"].values

        # Simple divergence: compare first half vs second half
        half = lookback // 2
        first_half_low = float(price_lows[:half].min())
        second_half_low = float(price_lows[half:].min())
        first_half_high = float(price_highs[:half].max())
        second_half_high = float(price_highs[half:].max())

        # We use MACD histogram from indicators (current) vs a rough estimate
        # For a proper implementation we'd need historical MACD, but we can
        # use the histogram sign and magnitude as a proxy
        macd_hist = indicators.macd_hist
        macd_signal_cross = indicators.macd - indicators.macd_signal

        side = None

        # Bullish divergence: price lower low, but MACD hist turning up
        if second_half_low < first_half_low and macd_hist > 0 and macd_signal_cross > 0:
            if not self._config.rsi_confirmation or indicators.rsi_14 < 45:
                side = "BUY"

        # Bearish divergence: price higher high, but MACD hist turning down
        elif second_half_high > first_half_high and macd_hist < 0 and macd_signal_cross < 0:
            if not self._config.rsi_confirmation or indicators.rsi_14 > 55:
                side = "SELL"

        if side is None:
            return None

        if side == "BUY":
            stop_loss = close - self._config.stop_loss_atr_multiplier * indicators.atr_14
            target = close + self._config.target_atr_multiplier * indicators.atr_14
        else:
            stop_loss = close + self._config.stop_loss_atr_multiplier * indicators.atr_14
            target = close - self._config.target_atr_multiplier * indicators.atr_14

        logger.info(
            f"MACDDivergence signal: {indicators.symbol} {side} " f"MACD_hist={macd_hist:.4f}",
        )
        return create_signal(
            symbol=indicators.symbol,
            strategy=self.name,
            side=side,
            entry_price=close,
            stop_loss=stop_loss,
            target=target,
            indicators=indicators,
        )


# ---------------------------------------------------------------------------
# 8. Parabolic SAR Trend Strategy
# ---------------------------------------------------------------------------
class ParabolicSARTrendStrategyImpl(Strategy):
    """Parabolic SAR + EMA alignment for trend continuation.

    BUY: SAR direction bullish (price above SAR) AND EMA9 > EMA21 > EMA50
         AND volume above average.
    SELL: SAR direction bearish AND EMA9 < EMA21 < EMA50.
    """

    def __init__(self, config: ParabolicSARConfig) -> None:
        self._config = config

    @property
    def name(self) -> str:
        return "ParabolicSARTrend"

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    def generate_signal(
        self,
        indicators: IndicatorSet,
        candles: pd.DataFrame,
    ) -> Signal | None:
        if not self._config.enabled or candles.empty:
            return None

        close = float(candles.iloc[-1]["close"])
        volume = float(candles.iloc[-1]["volume"])

        if volume < self._config.volume_multiplier * indicators.volume_avg_20:
            return None

        side = None
        if indicators.psar_direction == 1:  # Bullish SAR
            if self._config.require_ema_alignment:
                if indicators.ema_9 > indicators.ema_21 > indicators.ema_50:
                    side = "BUY"
            else:
                side = "BUY"
        elif indicators.psar_direction == -1:  # Bearish SAR
            if self._config.require_ema_alignment:
                if indicators.ema_9 < indicators.ema_21 < indicators.ema_50:
                    side = "SELL"
            else:
                side = "SELL"

        if side is None:
            return None

        if side == "BUY":
            stop_loss = indicators.psar  # SAR itself is the trailing stop
            target = close + self._config.target_atr_multiplier * indicators.atr_14
        else:
            stop_loss = indicators.psar
            target = close - self._config.target_atr_multiplier * indicators.atr_14

        logger.info(
            f"ParabolicSARTrend signal: {indicators.symbol} {side} "
            f"SAR={indicators.psar:.2f} dir={indicators.psar_direction}",
        )
        return create_signal(
            symbol=indicators.symbol,
            strategy=self.name,
            side=side,
            entry_price=close,
            stop_loss=stop_loss,
            target=target,
            indicators=indicators,
        )


# ---------------------------------------------------------------------------
# 9. Volume Breakout Strategy
# ---------------------------------------------------------------------------
class VolumeBreakoutStrategyImpl(Strategy):
    """Volume-confirmed breakout: enters when price breaks above/below
    a recent range with an extreme volume spike.

    BUY: close > highest high of lookback AND volume > spike_multiplier × avg
         AND MACD > 0.
    SELL: close < lowest low of lookback AND volume > spike_multiplier × avg
          AND MACD < 0.
    """

    def __init__(self, config: VolumeBreakoutConfig) -> None:
        self._config = config

    @property
    def name(self) -> str:
        return "VolumeBreakout"

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    def generate_signal(
        self,
        indicators: IndicatorSet,
        candles: pd.DataFrame,
    ) -> Signal | None:
        if not self._config.enabled or candles.empty:
            return None

        lookback = self._config.lookback_candles
        if len(candles) < lookback + 1:
            return None

        close = float(candles.iloc[-1]["close"])
        volume = float(candles.iloc[-1]["volume"])

        # Volume spike required
        if volume < self._config.volume_spike_multiplier * indicators.volume_avg_20:
            return None

        # Calculate range from lookback (excluding current candle)
        lookback_candles = candles.iloc[-(lookback + 1) : -1]
        range_high = float(lookback_candles["high"].max())
        range_low = float(lookback_candles["low"].min())

        side = None
        if close > range_high and indicators.macd > 0:
            side = "BUY"
        elif close < range_low and indicators.macd < 0:
            side = "SELL"

        if side is None:
            return None

        if side == "BUY":
            stop_loss = close - self._config.stop_loss_atr_multiplier * indicators.atr_14
            target = close + self._config.target_atr_multiplier * indicators.atr_14
        else:
            stop_loss = close + self._config.stop_loss_atr_multiplier * indicators.atr_14
            target = close - self._config.target_atr_multiplier * indicators.atr_14

        logger.info(
            f"VolumeBreakout signal: {indicators.symbol} {side} "
            f"vol_ratio={volume / indicators.volume_avg_20:.1f}x "
            f"range=({range_low:.2f}-{range_high:.2f})",
        )
        return create_signal(
            symbol=indicators.symbol,
            strategy=self.name,
            side=side,
            entry_price=close,
            stop_loss=stop_loss,
            target=target,
            indicators=indicators,
        )


# ---------------------------------------------------------------------------
# 10. Multi-Timeframe Momentum Confluence Strategy
# ---------------------------------------------------------------------------
class MultiTimeframeMomentumStrategyImpl(Strategy):
    """Confluence strategy: counts how many indicators agree on direction
    and only enters when a minimum threshold of alignment is met.

    Bullish signals counted:
    - EMA9 > EMA21, Supertrend bullish, MACD > signal, RSI > 50,
      price > VWAP, ADX > 20 with +DI > -DI, Stoch %K > 50,
      SAR bullish, Ichimoku TK cross bullish, CCI > 0.

    Requires min_indicators_aligned (default 5) to trigger.
    """

    def __init__(self, config: MTFMomentumConfig) -> None:
        self._config = config

    @property
    def name(self) -> str:
        return "MultiMomentum"

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    def generate_signal(
        self,
        indicators: IndicatorSet,
        candles: pd.DataFrame,
    ) -> Signal | None:
        if not self._config.enabled or candles.empty:
            return None

        close = float(candles.iloc[-1]["close"])

        # Count bullish signals
        bullish = 0
        bearish = 0

        # 1. EMA crossover
        if indicators.ema_9 > indicators.ema_21:
            bullish += 1
        else:
            bearish += 1

        # 2. Supertrend
        if indicators.supertrend_direction == 1:
            bullish += 1
        else:
            bearish += 1

        # 3. MACD vs signal
        if indicators.macd > indicators.macd_signal:
            bullish += 1
        else:
            bearish += 1

        # 4. RSI
        if indicators.rsi_14 > 50:
            bullish += 1
        else:
            bearish += 1

        # 5. Price vs VWAP
        if close > indicators.vwap:
            bullish += 1
        else:
            bearish += 1

        # 6. ADX + DI
        if indicators.adx > 20 and indicators.plus_di > indicators.minus_di:
            bullish += 1
        elif indicators.adx > 20 and indicators.minus_di > indicators.plus_di:
            bearish += 1

        # 7. Stochastic
        if indicators.stoch_k > 50:
            bullish += 1
        else:
            bearish += 1

        # 8. Parabolic SAR
        if indicators.psar_direction == 1:
            bullish += 1
        else:
            bearish += 1

        # 9. Ichimoku TK cross
        if indicators.ichimoku_tenkan > indicators.ichimoku_kijun:
            bullish += 1
        else:
            bearish += 1

        # 10. CCI
        if indicators.cci > 0:
            bullish += 1
        else:
            bearish += 1

        min_required = self._config.min_indicators_aligned
        side = None
        if bullish >= min_required:
            side = "BUY"
        elif bearish >= min_required:
            side = "SELL"

        if side is None:
            return None

        if side == "BUY":
            stop_loss = close - self._config.stop_loss_atr_multiplier * indicators.atr_14
            target = close + self._config.target_atr_multiplier * indicators.atr_14
        else:
            stop_loss = close + self._config.stop_loss_atr_multiplier * indicators.atr_14
            target = close - self._config.target_atr_multiplier * indicators.atr_14

        score = bullish if side == "BUY" else bearish
        logger.info(
            f"MultiMomentum signal: {indicators.symbol} {side} " f"confluence={score}/10",
        )
        return create_signal(
            symbol=indicators.symbol,
            strategy=self.name,
            side=side,
            entry_price=close,
            stop_loss=stop_loss,
            target=target,
            indicators=indicators,
        )
