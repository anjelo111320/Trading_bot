"""Breakdowns of a backtest: windows, groups, benchmarks and exit shapes."""

from collections.abc import Callable, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Final

from trading_intel.backtesting.benchmarks import ExitTemplate, exit_template
from trading_intel.backtesting.engine import BacktestTrade
from trading_intel.backtesting.metrics import ClosedTrade, Metrics, compute_metrics
from trading_intel.domain.candles import ClosedCandle

ZERO: Final = Decimal(0)
STARTING_EQUITY: Final = Decimal(10000)


def closed_trade(trade: BacktestTrade) -> ClosedTrade | None:
    outcome = trade.result
    if outcome.entry_time is None or outcome.exit_time is None:
        return None
    return ClosedTrade(
        entry_time=outcome.entry_time,
        exit_time=outcome.exit_time,
        net_pnl=outcome.net_pnl,
        r_multiple=outcome.net_pnl / trade.planned_risk if trade.planned_risk else ZERO,
        costs=outcome.fees - outcome.funding + outcome.spread_cost + outcome.slippage_cost,
        gross_pnl=outcome.gross_pnl,
    )


def metrics_for(trades: Sequence[BacktestTrade], days: int) -> Metrics:
    """Metrics for a subset, with its own equity curve from the same starting equity."""
    closed = sorted(
        (c for c in (closed_trade(t) for t in trades) if c is not None), key=lambda c: c.exit_time
    )
    equity = [STARTING_EQUITY]
    for trade in closed:
        equity.append(equity[-1] + trade.net_pnl)
    return compute_metrics(closed, equity, STARTING_EQUITY, max(days, 1))


def entered_between(
    trades: Sequence[BacktestTrade], start: datetime, end: datetime
) -> list[BacktestTrade]:
    return [
        t for t in trades if t.result.entry_time is not None and start <= t.result.entry_time < end
    ]


def group(
    trades: Sequence[BacktestTrade], key: Callable[[BacktestTrade], str]
) -> dict[str, list[BacktestTrade]]:
    groups: dict[str, list[BacktestTrade]] = {}
    for trade in trades:
        groups.setdefault(key(trade), []).append(trade)
    return dict(sorted(groups.items()))


def pattern_of(trade: BacktestTrade) -> str:
    patterns = trade.decision.patterns if trade.decision else ()
    return patterns[0].pattern_type if patterns else "unknown"


def side_of(trade: BacktestTrade) -> str:
    return trade.order.side.value


def buy_and_hold(daily: Sequence[ClosedCandle], start: datetime, end: datetime) -> float | None:
    """Return from the first open to the last close in the window, before any costs."""
    inside = [c for c in daily if start <= c.open_time and c.close_time < end]
    if not inside:
        return None
    return float(inside[-1].close / inside[0].open - 1)


def exit_templates(trades: Sequence[BacktestTrade]) -> list[ExitTemplate]:
    """The stop and target shapes of real trades, for the random-entry benchmark."""
    templates: list[ExitTemplate] = []
    for trade in trades:
        decision = trade.decision
        if decision is None or decision.setup_atr is None or decision.setup_atr <= 0:
            continue
        order = trade.order
        templates.append(exit_template(order.entry, order.stop, order.targets, decision.setup_atr))
    return templates
