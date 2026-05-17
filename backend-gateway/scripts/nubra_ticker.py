#!/usr/bin/env python3
"""Standalone Nubra WebSocket → Redis Streams bridge.

Runs as its own process alongside the gateway. Keeps the Nubra SDK
in its own Python interpreter where its threading model is well-
behaved, and publishes every orderbook tick to two Redis streams:

    stream:ticks                  # aggregate, consumed by the gateway's
                                  # redis_consumer → Socket.IO ``price_tick``
    stream:ticks:<SYMBOL>         # per-symbol, for strategy engines or
                                  # replay tooling

The gateway's redis_consumer maps either stream onto the same
``price_tick`` event shape (``{symbol, ltp, volume, timestamp}``),
so the browser dashboard doesn't care which one fired.

Usage
-----
From the repo root, with the project venv activated::

    cd backend-gateway
    python scripts/nubra_ticker.py

Environment
-----------
Loads ``backend-gateway/.env`` for these variables:

    NUBRA_PHONE_NO       required   Nubra account phone (for SDK auth)
    NUBRA_MPIN           required   4-digit MPIN
    NUBRA_ENV            optional   PROD (default) / UAT
    NUBRA_TOTP_SECRET    optional   when set, enables headless re-login
    REDIS_HOST           optional   default localhost
    REDIS_PORT           optional   default 6379
    REDIS_DB             optional   default 0
    NUBRA_TICK_SYMBOLS   optional   comma-separated override of the
                                    default watchlist

Lifecycle
---------
* ``InitNubraSdk`` runs once at startup. On a fresh process its
  ``input()`` fall-back path is harmless — stdin is a real TTY if you
  started the script interactively, or a closed FD if you started it
  via ``nohup``/a supervisor. Either way we do not share a process
  with uvicorn, so there's no event-loop contention.
* ``NubraDataSocket.connect()`` starts the SDK's internal asyncio
  loop on a dedicated thread. The subscribe frame is sent after a
  short settle delay so the handshake completes.
* SIGINT / SIGTERM triggers a clean socket close and process exit.

Operational notes
-----------------
* Nubra orderbook prices are in *paise*; we divide by 100 before
  publishing so the browser sees rupees.
* The publisher stays connected 24/7 but Nubra only pushes ticks
  during NSE market hours (09:15–15:30 IST on weekdays). Outside
  that window you'll see the "connected"/"subscribed" log lines but
  no tick volume.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ─── sys.path + .env bootstrap ──────────────────────────────────────────────
# Make the script runnable from any cwd by adding the gateway app root
# to sys.path and loading the local .env explicitly.
_THIS_DIR = Path(__file__).resolve().parent
_GATEWAY_ROOT = _THIS_DIR.parent
if str(_GATEWAY_ROOT) not in sys.path:
    sys.path.insert(0, str(_GATEWAY_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_GATEWAY_ROOT / ".env")

# Also propagate phone/MPIN/TOTP into the variable names the Nubra SDK
# looks up (``PHONE_NO``/``MPIN``/``TOTP_SECRET``) before importing any
# SDK module.
_phone = os.getenv("NUBRA_PHONE_NO", "")
_mpin = os.getenv("NUBRA_MPIN", "")
_totp = os.getenv("NUBRA_TOTP_SECRET", "")
if _phone:
    os.environ["PHONE_NO"] = _phone
if _mpin:
    os.environ["MPIN"] = _mpin
if _totp:
    os.environ["TOTP_SECRET"] = _totp


import redis  # noqa: E402

# ─── SSL certificate bundle ────────────────────────────────────────────────
# macOS Python framework installs often ship without a populated default
# cafile, which makes ``aiohttp`` (used by the Nubra WS client) fail with
# "unable to get local issuer certificate" on every connection attempt.
# Point ``SSL_CERT_FILE`` + ``SSL_CERT_DIR`` at the ``certifi`` bundle so
# both ``aiohttp`` and the stdlib ``ssl`` module agree on where to look.
try:
    import certifi

    _cert_path = certifi.where()
    os.environ.setdefault("SSL_CERT_FILE", _cert_path)
    os.environ.setdefault("SSL_CERT_DIR", os.path.dirname(_cert_path))
    os.environ.setdefault("REQUESTS_CA_BUNDLE", _cert_path)
except Exception:
    # certifi should always be installed (transitive dep of requests,
    # httpx, urllib3). If somehow it isn't, let the default ssl setup
    # raise its own error downstream.
    pass


# ─── Logging ────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("nubra_ticker")


# ─── Config ─────────────────────────────────────────────────────────────────

DEFAULT_SYMBOLS = [
    "RELIANCE",
    "TCS",
    "INFY",
    "HDFCBANK",
    "ICICIBANK",
    "SBIN",
    "ITC",
    "LT",
    "AXISBANK",
    "BHARTIARTL",
]

AGGREGATE_STREAM = "stream:ticks"
STREAM_MAXLEN = 5_000  # approximate trim
SUBSCRIPTION_POLL_SEC = 60  # reconcile desired vs subscribed every minute
SUBSCRIBE_SETTLE_SEC = 1.5  # wait for WS handshake before first subscribe


def _desired_symbols() -> list[str]:
    env_val = os.getenv("NUBRA_TICK_SYMBOLS", "").strip()
    if env_val:
        return [s.strip().upper() for s in env_val.split(",") if s.strip()]
    return list(DEFAULT_SYMBOLS)


# ─── Globals (single-process, so module state is fine) ──────────────────────

_redis_client: Optional[redis.Redis] = None
_socket = None
_instruments = None
_subscribed: set[str] = set()
_ref_id_to_symbol: dict[int, str] = {}
_running = True


# ─── Helpers ────────────────────────────────────────────────────────────────


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            db=int(os.getenv("REDIS_DB", "0")),
            decode_responses=True,
            socket_timeout=5.0,
            socket_connect_timeout=5.0,
        )
    return _redis_client


def _handle_orderbook_tick(payload) -> None:  # noqa: ANN001 — SDK types via msgspec
    """Callback invoked by NubraDataSocket for every orderbook update.

    The SDK hands us an ``OrderBookWrapper`` msgspec struct (not a dict),
    so we access fields via attributes. Translates to our canonical
    PriceTick shape and publishes it to both the aggregate and
    per-symbol Redis streams.
    """
    try:
        # Support both the msgspec struct shape we see in practice and
        # a plain ``dict`` (older SDK versions / future drift) so this
        # callback keeps working if the SDK authors ever rewrap.
        def _field(obj, name):
            if isinstance(obj, dict):
                return obj.get(name)
            return getattr(obj, name, None)

        ref_id = _field(payload, "ref_id")
        if ref_id is None:
            return
        symbol = _ref_id_to_symbol.get(int(ref_id))
        if not symbol:
            return

        ltp_paise = _field(payload, "last_traded_price")
        if ltp_paise is None:
            return
        ltp = float(ltp_paise) / 100.0

        volume = _field(payload, "volume")
        ts_ns = _field(payload, "timestamp")
        if ts_ns:
            try:
                dt = datetime.fromtimestamp(int(ts_ns) / 1_000_000_000, tz=timezone.utc)
                ts_iso = dt.isoformat()
            except (ValueError, OSError):
                ts_iso = datetime.now(timezone.utc).isoformat()
        else:
            ts_iso = datetime.now(timezone.utc).isoformat()

        fields = {
            "symbol": symbol,
            "ltp": f"{ltp:.2f}",
            "volume": str(volume) if volume is not None else "0",
            "timestamp": ts_iso,
        }

        r = _get_redis()
        r.xadd(AGGREGATE_STREAM, fields, maxlen=STREAM_MAXLEN, approximate=True)
        r.xadd(f"stream:ticks:{symbol}", fields, maxlen=STREAM_MAXLEN, approximate=True)
    except Exception:
        logger.exception("Failed to publish tick")


def _handle_error(msg: str) -> None:
    logger.warning("NubraDataSocket error: %s", msg)


def _handle_close(msg: str) -> None:
    logger.info("NubraDataSocket closed: %s", msg)


def _handle_connect(msg: str) -> None:
    logger.info("NubraDataSocket connected: %s", msg)


def _sync_subscriptions() -> None:
    """Reconcile live subscriptions against the desired set."""
    global _subscribed, _ref_id_to_symbol
    if _instruments is None or _socket is None:
        return

    from nubra_python_sdk.trading.trading_enum import ExchangeEnum

    desired = set(_desired_symbols())
    to_add = desired - _subscribed
    to_remove = _subscribed - desired

    if to_add:
        ref_ids: list[int] = []
        for sym in sorted(to_add):
            try:
                inst = _instruments.get_instrument_by_symbol(sym, exchange="NSE")
                if inst is None or not hasattr(inst, "ref_id"):
                    logger.info("No ref_id for %s — skipping", sym)
                    continue
                ref_id = int(inst.ref_id)
                ref_ids.append(ref_id)
                _ref_id_to_symbol[ref_id] = sym
            except Exception:
                logger.exception("ref_id lookup failed for %s", sym)

        if ref_ids:
            try:
                _socket.subscribe(
                    symbols=[str(r) for r in ref_ids],
                    data_type="orderbook",
                    exchange=ExchangeEnum.NSE,
                )
                _subscribed.update(
                    s
                    for s in to_add
                    if any(rid for rid in ref_ids if _ref_id_to_symbol.get(rid) == s)
                )
                logger.info(
                    "Subscribed %d symbols: %s",
                    len(ref_ids),
                    sorted(
                        s for s in to_add if any(_ref_id_to_symbol.get(rid) == s for rid in ref_ids)
                    ),
                )
            except Exception:
                logger.exception("Nubra subscribe failed for %s", sorted(to_add))

    if to_remove:
        ref_ids = [rid for rid, sym in _ref_id_to_symbol.items() if sym in to_remove]
        if ref_ids:
            try:
                _socket.unsubscribe(
                    symbols=[str(r) for r in ref_ids],
                    data_type="orderbook",
                    exchange=ExchangeEnum.NSE,
                )
                for rid in list(_ref_id_to_symbol.keys()):
                    if _ref_id_to_symbol[rid] in to_remove:
                        del _ref_id_to_symbol[rid]
                _subscribed.difference_update(to_remove)
                logger.info("Unsubscribed: %s", sorted(to_remove))
            except Exception:
                logger.exception("Nubra unsubscribe failed for %s", sorted(to_remove))


# ─── Main loop ──────────────────────────────────────────────────────────────


def _handle_signal(signum, frame):
    global _running
    logger.info("Signal %d received — shutting down", signum)
    _running = False


def main() -> int:
    global _socket, _instruments, _running

    if not _phone or not _mpin:
        logger.error("NUBRA_PHONE_NO and NUBRA_MPIN must be set in backend-gateway/.env")
        return 1

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    logger.info("Initializing Nubra SDK (cached session or TOTP)")
    from nubra_python_sdk.refdata.instruments import InstrumentData
    from nubra_python_sdk.start_sdk import InitNubraSdk, NubraEnv
    from nubra_python_sdk.ticker.websocketdata import NubraDataSocket

    nubra_env_str = os.getenv("NUBRA_ENV", "PROD").upper()
    nubra_env = NubraEnv.UAT if nubra_env_str == "UAT" else NubraEnv.PROD
    use_totp = bool(_totp)

    try:
        client = InitNubraSdk(nubra_env, totp_login=use_totp, env_creds=True)
    except Exception:
        logger.exception(
            "InitNubraSdk failed — ensure cached session is valid or set NUBRA_TOTP_SECRET"
        )
        return 2

    _instruments = InstrumentData(client)
    logger.info("Nubra SDK ready")

    _socket = NubraDataSocket(
        client=client,
        on_orderbook_data=_handle_orderbook_tick,
        on_error=_handle_error,
        on_close=_handle_close,
        on_connect=_handle_connect,
        reconnect=True,
        persist_subscriptions=True,
    )

    logger.info("Connecting WebSocket...")
    try:
        _socket.connect()
    except Exception:
        logger.exception("WebSocket connect failed")
        return 3

    # Let the handshake settle so the first subscribe frame lands on a
    # ready socket. Nubra's SDK queues subscribe calls made before
    # connect completes, but we want the log ordering to make sense.
    time.sleep(SUBSCRIBE_SETTLE_SEC)

    logger.info("Initial subscription sync")
    _sync_subscriptions()

    # Reconcile loop. Cheap + resilient: fixes any subscription drift,
    # keeps the process alive, and gives a clean place to catch the
    # shutdown signal.
    logger.info("Entering reconcile loop (tick updates are async)")
    while _running:
        # Sleep in short chunks so signals are responsive.
        for _ in range(SUBSCRIPTION_POLL_SEC):
            if not _running:
                break
            time.sleep(1)
        if _running:
            try:
                _sync_subscriptions()
            except Exception:
                logger.exception("Subscription sync errored")

    logger.info("Closing WebSocket...")
    try:
        _socket.close()
    except Exception:
        logger.exception("Error during socket close")
    logger.info("Bye.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
