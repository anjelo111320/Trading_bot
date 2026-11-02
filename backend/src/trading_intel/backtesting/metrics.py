"""Performance metrics, after all costs. Definitions are in docs/10-BACKTESTING.md."""

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Final

DAYS_PER_YEAR: Final = 365
BOOTSTRAP_RUNS: Final = 2000
BOOTSTRAP_SEED: Final = 7


@dataclass(frozen=True)
class ClosedTrade:
    entry_time: datetime
    exit_time: datetime
    net_pnl: Decimal
    r_multiple: Decimal
    costs: Decimal
    gross_pnl: Decimal


@dataclass(frozen=True)
class Metrics:
    trades: int
    net_pnl: Decimal
    total_return: float
    win_rate: float | None
    expectancy_r: float | None
    profit_factor: float | None
    average_reward_risk: float | None
    max_drawdown: float
    sharpe: float | None
    sortino: float | None
    cost_share: float | None
    expectancy_interval: tuple[float, float] | None


def maximum_drawdown(equity: Sequence[Decimal]) -> float:
    peak = equity[0]
    worst = Decimal(0)
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            worst = max(worst, (peak - value) / peak)
    return float(worst)


def daily_returns(
    trades: Sequence[ClosedTrade], starting_equity: Decimal, days: int
) -> list[float]:
    """Each day's P/L over that day's starting equity, including days with no trades."""
    if days <= 0:
        return []
    ordered = sorted(trades, key=lambda t: t.exit_time)
    first_day = min((t.exit_time.date() for t in ordered), default=None)
    by_day: dict[int, Decimal] = {}
    for trade in ordered:
        assert first_day is not None
        index = (trade.exit_time.date() - first_day).days
        by_day[index] = by_day.get(index, Decimal(0)) + trade.net_pnl
    equity = starting_equity
    results: list[float] = []
    for day in range(days):
        pnl = by_day.get(day, Decimal(0))
        results.append(float(pnl / equity) if equity > 0 else 0.0)
        equity += pnl
    return results


def _sharpe(returns: Sequence[float]) -> float | None:
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return mean / math.sqrt(variance) * math.sqrt(DAYS_PER_YEAR) if variance > 0 else None


def _sortino(returns: Sequence[float]) -> float | None:
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    downside = sum(min(r, 0.0) ** 2 for r in returns) / len(returns)
    return mean / math.sqrt(downside) * math.sqrt(DAYS_PER_YEAR) if downside > 0 else None


def bootstrap_interval(values: Sequence[float]) -> tuple[float, float] | None:
    """A seeded 95% interval for the mean, so reports are reproducible."""
    if len(values) < 2:
        return None
    rng = random.Random(BOOTSTRAP_SEED)  # noqa: S311
    count = len(values)
    means = sorted(sum(rng.choices(values, k=count)) / count for _ in range(BOOTSTRAP_RUNS))
    return means[int(BOOTSTRAP_RUNS * 0.025)], means[int(BOOTSTRAP_RUNS * 0.975) - 1]


def compute_metrics(
    trades: Sequence[ClosedTrade],
    equity_curve: Sequence[Decimal],
    starting_equity: Decimal,
    days: int,
) -> Metrics:
    """Only resolved, filled trades count, so unfilled orders cannot flatter the win rate."""
    net = sum((t.net_pnl for t in trades), Decimal(0))
    wins = [t for t in trades if t.net_pnl > 0]
    losses = [t for t in trades if t.net_pnl < 0]
    returns = daily_returns(trades, starting_equity, days)
    r_values = [float(t.r_multiple) for t in trades]
    gross_profit = sum((t.net_pnl for t in wins), Decimal(0))
    gross_loss = -sum((t.net_pnl for t in losses), Decimal(0))
    gross = sum((max(t.gross_pnl, Decimal(0)) for t in trades), Decimal(0))
    costs = sum((t.costs for t in trades), Decimal(0))
    average_win = sum(float(t.r_multiple) for t in wins) / len(wins) if wins else None
    average_loss = sum(float(t.r_multiple) for t in losses) / len(losses) if losses else None
    return Metrics(
        trades=len(trades),
        net_pnl=net,
        total_return=float(net / starting_equity),
        win_rate=len(wins) / len(trades) if trades else None,
        expectancy_r=sum(r_values) / len(r_values) if r_values else None,
        profit_factor=float(gross_profit / gross_loss) if gross_loss > 0 else None,
        average_reward_risk=(
            average_win / abs(average_loss) if average_win and average_loss else None
        ),
        max_drawdown=maximum_drawdown(equity_curve) if equity_curve else 0.0,
        sharpe=_sharpe(returns),
        sortino=_sortino(returns),
        cost_share=float(costs / gross) if gross > 0 else None,
        expectancy_interval=bootstrap_interval(r_values),
    )
