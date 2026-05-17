"""Signals endpoint — reads recent signals from Redis stream."""

from typing import Optional

from fastapi import APIRouter, Query

from app.services.redis_consumer import get_redis

router = APIRouter()

# Fields that should be returned as floats
_FLOAT_FIELDS = {"entry_price", "price", "stop_loss", "stopLoss", "target", "atr"}


def _coerce_signal(entry: dict) -> dict:
    """Convert Redis string values to proper types for JSON response."""
    out = {}
    for k, v in entry.items():
        if k in _FLOAT_FIELDS:
            try:
                out[k] = float(v)
            except (ValueError, TypeError):
                out[k] = v
        else:
            out[k] = v
    # Ensure frontend-expected field names exist
    if "entry_price" in out and "price" not in out:
        out["price"] = out["entry_price"]
    if "stop_loss" in out and "stopLoss" not in out:
        out["stopLoss"] = out["stop_loss"]
    return out


@router.get("/signals")
def list_signals(
    symbol: Optional[str] = Query(None),
    strategy: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """Get recent signals from Redis stream:signals."""
    try:
        r = get_redis()
        # Read latest entries from stream:signals (newest first)
        raw = r.xrevrange("stream:signals", count=limit * 2)
        signals = []
        for msg_id, fields in raw:
            entry = {k: v for k, v in fields.items()}
            entry["id"] = msg_id
            # Apply filters
            if symbol and entry.get("symbol") != symbol:
                continue
            if strategy and entry.get("strategy") != strategy:
                continue
            signals.append(_coerce_signal(entry))
            if len(signals) >= limit:
                break
        return signals
    except Exception:
        # Redis unavailable — return empty list instead of 500
        return []
