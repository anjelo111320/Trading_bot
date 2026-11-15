"""The Bot page's results for Binance demo over a period (D057): every figure the owner chose.

Only the bot's trades count. A trade no entry of the bot's opened, such as one placed by hand
on the demo site, is counted apart and left out of every figure.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final, Literal

from trading_intel.performance.results import (
    ZERO,
    Curve,
    EntryOrder,
    Fill,
    Funding,
    Streaks,
    Summary,
    Trade,
    breakdown,
    equity_curve,
    median_hold_hours,
    rebuild,
    streaks,
    summarise,
)

Period = Literal["7d", "30d", "all"]
SPANS: Final[dict[str, timedelta | None]] = {
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "all": None,
}


@dataclass(frozen=True)
class Report:
    period: Period
    since: datetime
    start_equity: Decimal
    summary: Summary
    by_coin: list[tuple[str, Summary]]
    by_strategy: list[tuple[str, Summary]]
    by_side: list[tuple[str, Summary]]
    by_day: list[tuple[str, Summary]]  # Newest day first.
    grid: list[tuple[str, str, Summary]]  # Strategy, coin.
    curve: Curve
    streaks: Streaks
    median_hold_hours: Decimal | None
    trades: list[Trade]  # Newest first.
    open_trades: int
    not_from_bot: int
    other_fees: dict[str, Decimal]
    last_fill_at: datetime | None


def build(
    fills: Sequence[Fill],
    funding: Sequence[Funding],
    entries: Sequence[EntryOrder],
    budget: Decimal,
    now: datetime,
    period: Period,
) -> Report:
    closed, still = rebuild(fills, funding, entries)
    bot = [t for t in closed if t.strategy is not None and t.closed_at is not None]
    span = SPANS[period]
    first = min((t.opened_at for t in bot), default=now)
    since = now - span if span is not None else first
    shown = [t for t in bot if t.closed_at is not None and t.closed_at >= since]
    earlier = sum((t.net for t in bot if t.closed_at is not None and t.closed_at < since), ZERO)
    other: dict[str, Decimal] = {}
    for trade in shown:
        for asset, amount in trade.other_fees.items():
            other[asset] = other.get(asset, ZERO) + amount
    days = breakdown(shown, lambda t: f"{t.closed_at:%Y-%m-%d}")
    cells = breakdown(shown, lambda t: f"{t.strategy}\t{t.symbol}")
    grid = [(*_pair(name), stats) for name, stats in cells]
    return Report(
        period=period,
        since=since,
        start_equity=budget + earlier,
        summary=summarise(shown),
        by_coin=breakdown(shown, lambda t: t.symbol),
        by_strategy=breakdown(shown, lambda t: t.strategy or ""),
        by_side=breakdown(shown, lambda t: t.side),
        by_day=sorted(days, key=lambda row: row[0], reverse=True),
        grid=grid,
        curve=equity_curve(shown, budget + earlier, since),
        streaks=streaks(shown),
        median_hold_hours=median_hold_hours(shown),
        trades=sorted(shown, key=lambda t: t.closed_at or now, reverse=True),
        open_trades=sum(1 for t in still if t.strategy is not None),
        not_from_bot=sum(1 for t in closed if t.strategy is None),
        other_fees=other,
        last_fill_at=max((f.filled_at for f in fills), default=None),
    )


def _pair(name: str) -> tuple[str, str]:
    strategy, _, symbol = name.partition("\t")
    return strategy, symbol
