"""Nubra.io SDK integration for market data (historical OHLCV + live quotes).

Nubra is an Indian stock broker API providing exchange-sourced NSE/BSE data.
Authentication requires phone + TOTP + MPIN (configured via .env).

When Nubra credentials are configured, this service is used as the PRIMARY
data source for chart and quote endpoints. yfinance + curl_cffi remain as
fallback when Nubra is unavailable or not configured.

Required .env variables:
    NUBRA_PHONE_NO   – Registered phone number
    NUBRA_MPIN       – 4-digit MPIN
    NUBRA_ENV        – "UAT" or "PROD" (default: PROD)

Optional (for TOTP-based automated login):
    NUBRA_TOTP_SECRET – TOTP secret from authenticator app setup
"""

import logging
import os
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# Module-level SDK client (singleton)
_nubra_client = None
_nubra_lock = threading.Lock()
_instruments = None
_market_data = None
_last_init_attempt: float = 0
_INIT_COOLDOWN = 300  # Don't retry init more than once per 5 min


def is_nubra_configured() -> bool:
    """Check if Nubra credentials are present in environment."""
    return bool(os.getenv("NUBRA_PHONE_NO") and os.getenv("NUBRA_MPIN"))


def _get_nubra_env():
    """Return the NubraEnv enum based on NUBRA_ENV env var."""
    from nubra_python_sdk.start_sdk import NubraEnv
    env_str = os.getenv("NUBRA_ENV", "PROD").upper()
    return NubraEnv.UAT if env_str == "UAT" else NubraEnv.PROD


def _init_nubra():
    """Initialize the Nubra SDK client (thread-safe, singleton).

    Uses TOTP login if NUBRA_TOTP_SECRET is set, otherwise OTP.
    The SDK reads PHONE_NO and MPIN from .env when env_creds=True.
    """
    global _nubra_client, _instruments, _market_data, _last_init_attempt

    if not is_nubra_configured():
        return None

    # Prefer TOTP login when a secret is configured (fully headless).
    # Otherwise, fall back to cached-session login: the SDK stores a
    # bearer token in ``auth_data.db`` after a successful interactive
    # login and re-uses it on subsequent boots until the session
    # expires. This lets the gateway start without a TOTP secret as
    # long as someone has completed an OTP login recently (via
    # ``scripts/nubra_setup_totp.py``).
    totp_secret = os.getenv("NUBRA_TOTP_SECRET", "")
    use_totp = bool(totp_secret)

    with _nubra_lock:
        if _nubra_client is not None:
            return _nubra_client

        now = time.time()
        if now - _last_init_attempt < _INIT_COOLDOWN:
            return None
        _last_init_attempt = now

        try:
            # Nubra SDK reads PHONE_NO and MPIN from .env
            # We need to set them in the format the SDK expects
            phone = os.getenv("NUBRA_PHONE_NO", "")
            mpin = os.getenv("NUBRA_MPIN", "")
            os.environ["PHONE_NO"] = phone
            os.environ["MPIN"] = mpin
            if totp_secret:
                os.environ["TOTP_SECRET"] = totp_secret

            from nubra_python_sdk.start_sdk import InitNubraSdk
            from nubra_python_sdk.refdata.instruments import InstrumentData
            from nubra_python_sdk.marketdata.market_data import MarketData

            nubra_env = _get_nubra_env()

            logger.info(
                "Initializing Nubra SDK (env=%s, totp=%s, cached_session=%s)",
                nubra_env, use_totp, not use_totp,
            )
            client = InitNubraSdk(nubra_env, totp_login=use_totp, env_creds=True)

            _instruments = InstrumentData(client)
            _market_data = MarketData(client)
            _nubra_client = client
            logger.info("Nubra SDK initialized successfully")
            return client

        except Exception as e:
            logger.warning("Nubra SDK init failed: %s", e)
            _nubra_client = None
            _instruments = None
            _market_data = None
            return None


def _get_ref_id(symbol: str, exchange: str = "NSE") -> Optional[int]:
    """Resolve a stock symbol to Nubra ref_id."""
    if _instruments is None:
        return None
    try:
        inst = _instruments.get_instrument_by_symbol(symbol.upper(), exchange=exchange)
        if inst and hasattr(inst, "ref_id"):
            return inst.ref_id
    except Exception as e:
        logger.debug("Nubra ref_id lookup failed for %s/%s: %s", symbol, exchange, e)
    return None


def _nubra_interval(interval: str) -> str:
    """Map our interval strings to Nubra interval format."""
    mapping = {
        "1m": "1m", "2m": "2m", "5m": "5m", "15m": "15m", "30m": "30m",
        "1h": "1h", "1d": "1d", "5d": "1d", "1wk": "1w", "1mo": "1mt",
    }
    return mapping.get(interval, "1d")


def _period_to_dates(period: str) -> tuple[str, str]:
    """Convert yfinance-style period string to (startDate, endDate) ISO strings."""
    now = datetime.now(timezone.utc)
    end = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    period_map = {
        "1d": timedelta(days=1),
        "5d": timedelta(days=5),
        "1mo": timedelta(days=30),
        "3mo": timedelta(days=90),
        "6mo": timedelta(days=180),
        "1y": timedelta(days=365),
        "2y": timedelta(days=730),
        "5y": timedelta(days=1825),
        "10y": timedelta(days=3650),
        "max": timedelta(days=3650),
    }
    delta = period_map.get(period, timedelta(days=30))
    start = (now - delta).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return start, end


def fetch_chart_nubra(symbol: str, period: str, interval: str) -> Optional[dict]:
    """Fetch OHLCV chart data from Nubra.

    Returns dict matching our ChartResponse format, or None if unavailable.
    """
    if _market_data is None:
        if _init_nubra() is None:
            return None

    if _market_data is None:
        return None

    start_date, end_date = _period_to_dates(period)
    nubra_interval = _nubra_interval(interval)
    is_intraday = interval not in ("1d", "5d", "1wk", "1mo")

    # Nubra intraday data only goes back 3 months
    if is_intraday:
        three_months_ago = datetime.now(timezone.utc) - timedelta(days=90)
        start_dt = datetime.fromisoformat(start_date.replace(".000Z", "+00:00"))
        if start_dt < three_months_ago:
            start_date = three_months_ago.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    # Try NSE first, then BSE
    for exchange in ("NSE", "BSE"):
        try:
            resp = _market_data.historical_data({
                "exchange": exchange,
                "type": "STOCK",
                "values": [symbol.upper()],
                "fields": ["open", "high", "low", "close", "cumulative_volume"],
                "interval": nubra_interval,
                "startDate": start_date,
                "endDate": end_date,
                "intraDay": is_intraday,
                "realTime": False,
            })

            if not resp or not hasattr(resp, "result") or not resp.result:
                continue

            chart = resp.result[0].values[0].get(symbol.upper())
            if not chart or not hasattr(chart, "open") or not chart.open:
                continue

            bars = []
            import pandas as pd
            for i in range(len(chart.open)):
                ts = chart.open[i].timestamp
                # Nubra timestamps are in nanoseconds
                dt = pd.to_datetime(ts, unit="ns")

                o = chart.open[i].value / 100  # Nubra prices in paise
                h = chart.high[i].value / 100
                l = chart.low[i].value / 100
                c = chart.close[i].value / 100
                v = chart.cumulative_volume[i].value if hasattr(chart, "cumulative_volume") and i < len(chart.cumulative_volume) else 0

                if interval in ("1d", "5d", "1wk", "1mo", "1mt"):
                    time_str = dt.strftime("%Y-%m-%d")
                else:
                    time_str = dt.strftime("%Y-%m-%dT%H:%M:%S")

                bars.append({
                    "time": time_str,
                    "open": round(float(o), 2),
                    "high": round(float(h), 2),
                    "low": round(float(l), 2),
                    "close": round(float(c), 2),
                    "volume": int(v),
                })

            if not bars:
                continue

            current_price = bars[-1]["close"]
            previous_close = bars[-2]["close"] if len(bars) > 1 else None
            change = round(current_price - previous_close, 2) if previous_close else None
            change_pct = round((change / previous_close) * 100, 2) if change and previous_close else None

            logger.info("Nubra chart OK: %s %s/%s (%d bars)", symbol, period, interval, len(bars))
            return {
                "symbol": symbol.upper(),
                "period": period,
                "interval": interval,
                "bars": bars,
                "count": len(bars),
                "current_price": current_price,
                "previous_close": previous_close,
                "change": change,
                "change_percent": change_pct,
            }

        except Exception as e:
            logger.debug("Nubra chart %s/%s failed: %s", symbol, exchange, e)
            continue

    return None


def fetch_quote_nubra(symbol: str) -> Optional[dict]:
    """Fetch live quote from Nubra.

    Returns dict matching our LiveQuoteResponse format, or None if unavailable.
    """
    if _market_data is None:
        if _init_nubra() is None:
            return None

    if _market_data is None:
        return None

    # Try NSE first, then BSE
    for exchange in ("NSE", "BSE"):
        ref_id = _get_ref_id(symbol, exchange)
        if ref_id is None:
            continue

        try:
            quote = _market_data.quote(ref_id=ref_id, levels=0)
            if not quote or not hasattr(quote, "orderBook"):
                continue

            ob = quote.orderBook
            # Nubra prices are in paise (1/100 of rupee)
            ltp = ob.last_traded_price / 100 if ob.last_traded_price else None
            prev_close = None

            # Try to get prev_close from instrument data
            try:
                inst = _instruments.get_instrument_by_ref_id(ref_id)
                if inst and hasattr(inst, "underlying_prev_close") and inst.underlying_prev_close:
                    prev_close = inst.underlying_prev_close / 100
            except Exception:
                pass

            if not ltp:
                continue

            change = round(ltp - prev_close, 2) if prev_close else None
            change_pct = round((change / prev_close) * 100, 2) if change and prev_close else None

            # Extract high/low from order book if available
            day_high = None
            day_low = None

            logger.info("Nubra quote OK: %s = %.2f", symbol, ltp)
            return {
                "symbol": symbol.upper(),
                "current_price": round(float(ltp), 2),
                "previous_close": round(float(prev_close), 2) if prev_close else None,
                "change": change,
                "change_percent": change_pct,
                "day_high": day_high,
                "day_low": day_low,
                "open_price": None,
                "volume": ob.volume if hasattr(ob, "volume") else None,
                "market_cap": None,
                "pe_ratio": None,
                "high_52w": None,
                "low_52w": None,
            }

        except Exception as e:
            logger.debug("Nubra quote %s/%s failed: %s", symbol, exchange, e)
            continue

    return None
