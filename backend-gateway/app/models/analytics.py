"""Analytics response models."""

from datetime import date

from app.models.base import CamelModel


class EquityCurvePoint(CamelModel):
    date: date
    cumulative_pnl: float


class DailyPnL(CamelModel):
    date: date
    pnl: float
    trades_count: int


class StrategyMetrics(CamelModel):
    strategy: str
    total_pnl: float
    win_rate: float
    avg_profit: float
    max_drawdown: float
    trades_count: int
