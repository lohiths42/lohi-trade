"""Analytics computations from trade data."""

from typing import Any, Dict, List
from collections import defaultdict
from datetime import date, timedelta

from app.services.db_service import get_trades


def get_equity_curve(start_date: str = None, end_date: str = None) -> List[Dict[str, Any]]:
    """Compute cumulative P&L equity curve from completed trades."""
    trades = get_trades(start_date, end_date)
    if not trades:
        return []

    daily_pnl: Dict[str, float] = defaultdict(float)
    for t in trades:
        if t.get("exit_time") and t.get("realized_pnl") is not None:
            day = str(t["exit_time"])[:10]
            daily_pnl[day] += t["realized_pnl"]

    cumulative = 0.0
    curve = []
    for day in sorted(daily_pnl.keys()):
        cumulative += daily_pnl[day]
        curve.append({"date": day, "cumulative_pnl": round(cumulative, 2)})
    return curve


def get_daily_pnl(days: int = 30) -> List[Dict[str, Any]]:
    """Get daily P&L for the last N days."""
    end = date.today()
    start = end - timedelta(days=days)
    trades = get_trades(start.isoformat(), end.isoformat())

    daily: Dict[str, Dict] = defaultdict(lambda: {"pnl": 0.0, "count": 0})
    for t in trades:
        if t.get("exit_time") and t.get("realized_pnl") is not None:
            day = str(t["exit_time"])[:10]
            daily[day]["pnl"] += t["realized_pnl"]
            daily[day]["count"] += 1

    return [
        {"date": day, "pnl": round(v["pnl"], 2), "trades_count": v["count"]}
        for day, v in sorted(daily.items())
    ]


def get_strategy_performance() -> List[Dict[str, Any]]:
    """Get performance metrics per strategy."""
    trades = get_trades()
    if not trades:
        return []

    by_strategy: Dict[str, List] = defaultdict(list)
    for t in trades:
        if t.get("realized_pnl") is not None:
            by_strategy[t["strategy"]].append(t["realized_pnl"])

    results = []
    for strategy, pnls in by_strategy.items():
        wins = [p for p in pnls if p > 0]
        total = sum(pnls)
        count = len(pnls)
        win_rate = (len(wins) / count * 100) if count > 0 else 0
        avg_profit = total / count if count > 0 else 0

        # Simple max drawdown
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for p in pnls:
            cumulative += p
            peak = max(peak, cumulative)
            dd = peak - cumulative
            max_dd = max(max_dd, dd)

        results.append({
            "strategy": strategy,
            "total_pnl": round(total, 2),
            "win_rate": round(win_rate, 1),
            "avg_profit": round(avg_profit, 2),
            "max_drawdown": round(max_dd, 2),
            "trades_count": count,
        })
    return results
