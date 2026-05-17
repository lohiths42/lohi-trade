"""LOHI-TRADE Streamlit Dashboard.

Single-page dashboard with auto-refresh every 5 seconds.
Displays P&L, positions, signals, trades, bias, and system health.

Run with: streamlit run src/ui/dashboard.py

Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6, 17.7, 13.4
"""

import sqlite3
import time
from datetime import datetime
from typing import Any

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# Page config (must be first Streamlit call)
# ---------------------------------------------------------------------------
st.set_page_config(page_title="LOHI-TRADE Dashboard", layout="wide")

# ---------------------------------------------------------------------------
# Helpers – connection factories (cached so they survive reruns)
# ---------------------------------------------------------------------------

MARKET_OPEN = "09:15"
MARKET_CLOSE = "15:30"


@st.cache_resource
def _get_sqlite_connection() -> sqlite3.Connection | None:
    """Return a shared SQLite connection (WAL mode, Row factory)."""
    try:
        conn = sqlite3.connect("data/lohi_trade.db", check_same_thread=False, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn
    except Exception:
        return None


@st.cache_resource
def _get_redis():
    """Return a raw redis.Redis client for dashboard reads."""
    try:
        import redis

        client = redis.Redis(
            host="localhost",
            port=6379,
            db=0,
            decode_responses=True,
            socket_timeout=2,
        )
        client.ping()
        return client
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Data-fetching helpers
# ---------------------------------------------------------------------------


def _query_sqlite(query: str, params: tuple = ()) -> list[dict[str, Any]]:
    """Run a read query against SQLite and return list of dicts."""
    conn = _get_sqlite_connection()
    if conn is None:
        return []
    try:
        cur = conn.execute(query, params)
        cols = [d[0] for d in cur.description] if cur.description else []
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception:
        return []


def _get_realized_pnl_today() -> float:
    today = datetime.now().strftime("%Y-%m-%d")
    rows = _query_sqlite(
        "SELECT COALESCE(SUM(realized_pnl), 0) AS total "
        "FROM trades WHERE DATE(exit_time) = ? AND realized_pnl IS NOT NULL",
        (today,),
    )
    return float(rows[0]["total"]) if rows else 0.0


def _get_open_positions() -> list[dict[str, Any]]:
    return _query_sqlite("SELECT * FROM trades WHERE exit_time IS NULL ORDER BY entry_time DESC")


def _get_recent_trades(limit: int = 50) -> list[dict[str, Any]]:
    return _query_sqlite(
        "SELECT * FROM trades WHERE exit_time IS NOT NULL ORDER BY exit_time DESC LIMIT ?",
        (limit,),
    )


def _get_unrealized_pnl(positions: list[dict[str, Any]]) -> float:
    """Estimate unrealized P&L using current prices from Redis."""
    r = _get_redis()
    if r is None or not positions:
        return 0.0
    total = 0.0
    for pos in positions:
        try:
            price_str = r.get(f"price:{pos['symbol']}")
            if price_str is None:
                continue
            current = float(price_str)
            entry = float(pos["entry_price"])
            qty = int(pos["quantity"])
            side_mult = 1 if pos["side"].upper() == "BUY" else -1
            total += side_mult * (current - entry) * qty
        except Exception:
            continue
    return total


def _get_recent_signals(count: int = 20) -> list[dict[str, Any]]:
    """Read last *count* signals from Redis stream:signals."""
    r = _get_redis()
    if r is None:
        return []
    try:
        raw = r.xrevrange("stream:signals", count=count)
        signals = []
        for msg_id, fields in raw:
            fields["id"] = msg_id
            signals.append(fields)
        return signals
    except Exception:
        return []


def _get_bias_for_symbols() -> list[dict[str, Any]]:
    """Read bias:{symbol} keys from Redis."""
    r = _get_redis()
    if r is None:
        return []
    try:
        keys = [k for k in r.keys("bias:*")]
        results = []
        for key in sorted(keys):
            symbol = key.replace("bias:", "", 1)
            value = r.get(key)
            results.append({"symbol": symbol, "bias": value or "—"})
        return results
    except Exception:
        return []


def _market_status() -> str:
    now = datetime.now().strftime("%H:%M")
    return "🟢 OPEN" if MARKET_OPEN <= now <= MARKET_CLOSE else "🔴 CLOSED"


def _redis_healthy() -> bool:
    r = _get_redis()
    if r is None:
        return False
    try:
        return r.ping()
    except Exception:
        return False


def _sqlite_healthy() -> bool:
    conn = _get_sqlite_connection()
    if conn is None:
        return False
    try:
        conn.execute("SELECT 1")
        return True
    except Exception:
        return False


def _last_tick_time() -> str:
    r = _get_redis()
    if r is None:
        return "—"
    try:
        val = r.get("last_tick_time")
        return val or "—"
    except Exception:
        return "—"


def _kill_switch_status() -> tuple[bool, str | None]:
    """Return (is_active, reason)."""
    r = _get_redis()
    if r is None:
        return False, None
    try:
        active = r.get("killswitch:active") == "true"
        reason = r.get("killswitch:reason")
        return active, reason
    except Exception:
        return False, None


def _activate_kill_switch(reason: str = "Manual activation via Dashboard") -> None:
    r = _get_redis()
    if r is None:
        return
    try:
        r.set("killswitch:active", "true")
        r.set("killswitch:reason", reason)
    except Exception:
        pass


def _deactivate_kill_switch() -> None:
    r = _get_redis()
    if r is None:
        return
    try:
        r.set("killswitch:active", "false")
        r.delete("killswitch:reason")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Dashboard layout
# ---------------------------------------------------------------------------


def _pnl_color(value: float) -> str:
    if value > 0:
        return "green"
    if value < 0:
        return "red"
    return "grey"


def render_header():
    """Header row: time, market status, kill switch."""
    ks_active, ks_reason = _kill_switch_status()

    col_time, col_market, col_ks = st.columns([2, 1, 2])
    with col_time:
        st.markdown(f"### 🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    with col_market:
        st.markdown(f"### {_market_status()}")
    with col_ks:
        if ks_active:
            st.error(f"⚠️ Kill Switch ACTIVE — {ks_reason or 'No reason'}")
            if st.button("🔓 Deactivate Kill Switch"):
                _deactivate_kill_switch()
                st.rerun()
        elif st.button("🛑 Activate Kill Switch"):
            st.session_state["ks_confirm"] = True

    # Confirmation dialog
    if st.session_state.get("ks_confirm"):
        st.warning("Are you sure you want to activate the kill switch? This will halt all trading.")
        c1, c2, _ = st.columns([1, 1, 4])
        with c1:
            if st.button("✅ Yes, activate"):
                _activate_kill_switch()
                st.session_state["ks_confirm"] = False
                st.rerun()
        with c2:
            if st.button("❌ Cancel"):
                st.session_state["ks_confirm"] = False
                st.rerun()


def render_pnl_cards():
    """P&L metrics row."""
    positions = _get_open_positions()
    realized = _get_realized_pnl_today()
    unrealized = _get_unrealized_pnl(positions)
    total = realized + unrealized

    c1, c2, c3 = st.columns(3)
    c1.metric("Realized P&L", f"₹{realized:,.2f}", delta=f"₹{realized:,.2f}")
    c2.metric("Unrealized P&L", f"₹{unrealized:,.2f}", delta=f"₹{unrealized:,.2f}")
    c3.metric("Total P&L", f"₹{total:,.2f}", delta=f"₹{total:,.2f}")


def render_positions_table():
    """Open positions table."""
    st.subheader("📊 Open Positions")
    positions = _get_open_positions()
    if not positions:
        st.info("No open positions.")
        return

    r = _get_redis()
    rows = []
    for pos in positions:
        current_price = None
        if r:
            try:
                p = r.get(f"price:{pos['symbol']}")
                if p:
                    current_price = float(p)
            except Exception:
                pass

        entry = float(pos["entry_price"])
        pnl_pct = ((current_price - entry) / entry * 100) if current_price else None
        if pos["side"].upper() == "SELL" and pnl_pct is not None:
            pnl_pct = -pnl_pct

        rows.append(
            {
                "Symbol": pos["symbol"],
                "Side": pos["side"],
                "Strategy": pos["strategy"],
                "Qty": pos["quantity"],
                "Entry": f"₹{entry:,.2f}",
                "Current": f"₹{current_price:,.2f}" if current_price else "—",
                "P&L %": f"{pnl_pct:+.2f}%" if pnl_pct is not None else "—",
                "Stop Loss": f"₹{float(pos['stop_loss']):,.2f}",
                "Target": f"₹{float(pos['target']):,.2f}",
                "Entry Time": pos["entry_time"],
            },
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_signals_table():
    """Recent signals table."""
    st.subheader("📡 Recent Signals (last 20)")
    signals = _get_recent_signals(20)
    if not signals:
        st.info("No recent signals.")
        return
    df = pd.DataFrame(signals)
    st.dataframe(df, use_container_width=True, hide_index=True)


def render_trades_table():
    """Recent closed trades table."""
    st.subheader("📈 Recent Trades (last 50)")
    trades = _get_recent_trades(50)
    if not trades:
        st.info("No recent trades.")
        return

    rows = []
    for t in trades:
        pnl = float(t["realized_pnl"]) if t.get("realized_pnl") is not None else None
        rows.append(
            {
                "Symbol": t["symbol"],
                "Side": t["side"],
                "Strategy": t["strategy"],
                "Qty": t["quantity"],
                "Entry": f"₹{float(t['entry_price']):,.2f}",
                "Exit": f"₹{float(t['exit_price']):,.2f}" if t.get("exit_price") else "—",
                "P&L": f"₹{pnl:,.2f}" if pnl is not None else "—",
                "Exit Reason": t.get("exit_reason", "—"),
                "Exit Time": t.get("exit_time", "—"),
            },
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_bias_table():
    """Current bias for all symbols."""
    st.subheader("🧭 Symbol Bias")
    bias_data = _get_bias_for_symbols()
    if not bias_data:
        st.info("No bias data available.")
        return
    df = pd.DataFrame(bias_data)
    st.dataframe(df, use_container_width=True, hide_index=True)


def render_system_health():
    """System health indicators."""
    st.subheader("🩺 System Health")
    c1, c2, c3 = st.columns(3)
    with c1:
        ok = _redis_healthy()
        st.metric("Redis", "✅ Connected" if ok else "❌ Disconnected")
    with c2:
        ok = _sqlite_healthy()
        st.metric("SQLite", "✅ Connected" if ok else "❌ Disconnected")
    with c3:
        tick = _last_tick_time()
        st.metric("Last Tick", tick)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    st.title("LOHI-TRADE Dashboard")

    render_header()
    st.divider()

    render_pnl_cards()
    st.divider()

    left, right = st.columns(2)
    with left:
        render_positions_table()
    with right:
        render_bias_table()

    st.divider()

    render_signals_table()
    st.divider()

    render_trades_table()
    st.divider()

    render_system_health()

    # Auto-refresh every 5 seconds
    time.sleep(5)
    st.rerun()


if __name__ == "__main__":
    main()
else:
    # When run via `streamlit run`, __name__ is "__main__" but Streamlit
    # also executes the module top-level. Call main() unconditionally so
    # the dashboard renders in both cases.
    main()
