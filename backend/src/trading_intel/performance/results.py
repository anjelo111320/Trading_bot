"""Completed trades rebuilt from Binance's own fills, and the results the Bot page shows (D057).

Binance reports fills, not trades. A trade here is one position on a coin, from the fill that
opens it to the fill that leaves it flat. Its result is what Binance booked: realized profit,
less fees, plus funding received while it was open. A trade is the bot's when its opening
fill belongs to an entry order the bot sent, which also gives its strategy and planned risk.
Pure and deterministic: no I/O.
"""

import statistics
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Final, Literal

ZERO: Final = Decimal(0)
FEE_ASSET: Final = "USDT"


@dataclass(frozen=True)
class Fill:
    symbol: str
    trade_id: int
    order_id: int
    side: Literal["BUY", "SELL"]
    price: Decimal
    quantity: Decimal
    realized_pnl: Decimal
    commission: Decimal
    commission_asset: str
    filled_at: datetime

    @property
    def signed(self) -> Decimal:
        return self.quantity if self.side == "BUY" else -self.quantity


@dataclass(frozen=True)
class Funding:
    symbol: str
    amount: Decimal  # Positive when received.
    paid_at: datetime


@dataclass(frozen=True)
class EntryOrder:
    """An entry order the bot sent, by Binance's order ID."""

    order_id: int
    strategy: str
    planned_risk: Decimal | None


@dataclass
class Trade:
    symbol: str
    side: Literal["LONG", "SHORT"]
    opened_at: datetime
    opening_order: int
    strategy: str | None = None  # None when no entry of the bot's opened it.
    planned_risk: Decimal | None = None
    closed_at: datetime | None = None
    size: Decimal = ZERO  # The largest size held.
    bought: Decimal = ZERO  # Quantity and value on each side, for average prices.
    bought_value: Decimal = ZERO
    sold: Decimal = ZERO
    sold_value: Decimal = ZERO
    pnl: Decimal = ZERO
    fees: Decimal = ZERO
    other_fees: dict[str, Decimal] = field(default_factory=dict)  # Fees in another asset.
    funding: Decimal = ZERO

    @property
    def net(self) -> Decimal:
        return self.pnl - self.fees + self.funding

    @property
    def won(self) -> bool:
        return self.net > 0

    @property
    def r(self) -> Decimal | None:
        if self.planned_risk is None or self.planned_risk <= 0:
            return None
        return self.net / self.planned_risk

    @property
    def entry_price(self) -> Decimal | None:
        quantity, value = (
            (self.bought, self.bought_value)
            if self.side == "LONG"
            else (self.sold, self.sold_value)
        )
        return value / quantity if quantity else None

    @property
    def exit_price(self) -> Decimal | None:
        quantity, value = (
            (self.sold, self.sold_value)
            if self.side == "LONG"
            else (self.bought, self.bought_value)
        )
        return value / quantity if quantity else None

    def _take(self, fill: Fill, quantity: Decimal, profit: bool) -> None:
        """Add `quantity` of the fill. Its fee is split by size; its realized profit, which
        only a closing fill has, goes whole to the trade it closes."""
        share = quantity / fill.quantity
        if fill.side == "BUY":
            self.bought += quantity
            self.bought_value += quantity * fill.price
        else:
            self.sold += quantity
            self.sold_value += quantity * fill.price
        if profit:
            self.pnl += fill.realized_pnl
        if fill.commission_asset == FEE_ASSET:
            self.fees += fill.commission * share
        else:
            asset = fill.commission_asset
            self.other_fees[asset] = self.other_fees.get(asset, ZERO) + fill.commission * share


def rebuild(
    fills: Iterable[Fill], funding: Iterable[Funding], entries: Iterable[EntryOrder]
) -> tuple[list[Trade], list[Trade]]:
    """Completed trades and still-open trades, from every fill, in time order per coin.

    A fill that takes a position through flat closes the trade at that fill and opens the next
    one with the rest; its profit belongs to the closing part, and its fee is split by size.
    """
    by_order = {entry.order_id: entry for entry in entries}
    closed: list[Trade] = []
    open_: dict[str, Trade] = {}
    position: dict[str, Decimal] = {}
    for fill in sorted(fills, key=lambda f: (f.filled_at, f.symbol, f.trade_id)):
        held = position.get(fill.symbol, ZERO)
        moved = fill.signed
        if held == 0 or (held > 0) == (moved > 0):
            trade = open_.get(fill.symbol) or _open(fill, by_order)
            open_[fill.symbol] = trade
            trade._take(fill, fill.quantity, profit=True)
            held += moved
            trade.size = max(trade.size, abs(held))
        else:
            closing = min(abs(moved), abs(held))
            trade = open_[fill.symbol]
            trade._take(fill, closing, profit=True)
            held += moved
            if held == 0 or (held > 0) == (moved > 0):
                trade.closed_at = fill.filled_at
                closed.append(open_.pop(fill.symbol))
            if held != 0 and (held > 0) == (moved > 0):
                rest = abs(held)
                flipped = _open(fill, by_order)
                flipped._take(fill, rest, profit=False)
                flipped.size = rest
                open_[fill.symbol] = flipped
        position[fill.symbol] = held
    _add_funding(closed + list(open_.values()), funding)
    return closed, list(open_.values())


def _open(fill: Fill, by_order: dict[int, EntryOrder]) -> Trade:
    entry = by_order.get(fill.order_id)
    return Trade(
        symbol=fill.symbol,
        side="LONG" if fill.side == "BUY" else "SHORT",
        opened_at=fill.filled_at,
        opening_order=fill.order_id,
        strategy=None if entry is None else entry.strategy,
        planned_risk=None if entry is None else entry.planned_risk,
    )


def _add_funding(trades: Sequence[Trade], funding: Iterable[Funding]) -> None:
    """Each payment goes to the trade open on its coin at that moment, if any."""
    for payment in funding:
        for trade in trades:
            ends = trade.closed_at
            if (
                trade.symbol == payment.symbol
                and trade.opened_at <= payment.paid_at
                and (ends is None or payment.paid_at <= ends)
            ):
                trade.funding += payment.amount
                break


@dataclass(frozen=True)
class Summary:
    trades: int
    wins: int
    win_rate: Decimal | None
    net: Decimal
    pnl: Decimal
    fees: Decimal
    funding: Decimal
    average_r: Decimal | None
    average_win: Decimal | None
    average_loss: Decimal | None
    profit_factor: Decimal | None  # None when nothing was lost.
    best: Decimal | None
    worst: Decimal | None

    @property
    def losses(self) -> int:
        return self.trades - self.wins


def summarise(trades: Sequence[Trade]) -> Summary:
    wins = [t.net for t in trades if t.won]
    losses = [t.net for t in trades if not t.won]
    rs = [r for t in trades if (r := t.r) is not None]
    lost = -sum(losses, ZERO)
    return Summary(
        trades=len(trades),
        wins=len(wins),
        win_rate=Decimal(len(wins)) / len(trades) if trades else None,
        net=sum((t.net for t in trades), ZERO),
        pnl=sum((t.pnl for t in trades), ZERO),
        fees=sum((t.fees for t in trades), ZERO),
        funding=sum((t.funding for t in trades), ZERO),
        average_r=sum(rs, ZERO) / len(rs) if rs else None,
        average_win=sum(wins, ZERO) / len(wins) if wins else None,
        average_loss=sum(losses, ZERO) / len(losses) if losses else None,
        profit_factor=sum(wins, ZERO) / lost if lost > 0 else None,
        best=max((t.net for t in trades), default=None),
        worst=min((t.net for t in trades), default=None),
    )


def breakdown(trades: Sequence[Trade], key: Callable[[Trade], str]) -> list[tuple[str, Summary]]:
    """Results per group, the most profitable group first."""
    groups: dict[str, list[Trade]] = {}
    for trade in trades:
        groups.setdefault(key(trade), []).append(trade)
    rows = [(name, summarise(group)) for name, group in groups.items()]
    return sorted(rows, key=lambda row: (-row[1].net, row[0]))


@dataclass(frozen=True)
class Curve:
    points: tuple[tuple[datetime, Decimal], ...]  # Equity after each closed trade.
    drawdown: Decimal  # The deepest fall from a high, in USDT.
    drawdown_fraction: Decimal | None


def equity_curve(trades: Sequence[Trade], start: Decimal, since: datetime) -> Curve:
    """Equity from `start` at `since`, stepping at each trade's close."""
    points: list[tuple[datetime, Decimal]] = [(since, start)]
    equity = peak = start
    deepest, deepest_fraction = ZERO, None
    for trade in sorted(trades, key=lambda t: (t.closed_at or since, t.symbol)):
        equity += trade.net
        points.append((trade.closed_at or since, equity))
        peak = max(peak, equity)
        fall = peak - equity
        if fall > deepest:
            deepest = fall
            deepest_fraction = fall / peak if peak > 0 else None
    return Curve(tuple(points), deepest, deepest_fraction)


def highest_equity(trades: Sequence[Trade], start: Decimal) -> Decimal:
    """The highest equity the bot's closed trades reached from `start`, for a loss stop that
    follows profits (D058). Open trades' swings do not count."""
    equity = high = start
    mine = (t for t in trades if t.strategy is not None and t.closed_at is not None)
    for trade in sorted(mine, key=lambda t: (t.closed_at, t.symbol)):
        equity += trade.net
        high = max(high, equity)
    return high


@dataclass(frozen=True)
class Streaks:
    longest_wins: int
    longest_losses: int
    current: int  # Positive for a winning run, negative for a losing run.


def streaks(trades: Sequence[Trade]) -> Streaks:
    best = worst = run = 0
    for trade in sorted(trades, key=lambda t: t.closed_at or t.opened_at):
        step = 1 if trade.won else -1
        run = run + step if run * step > 0 else step
        best, worst = max(best, run), min(worst, run)
    return Streaks(best, -worst, run)


def median_hold_hours(trades: Sequence[Trade]) -> Decimal | None:
    hours = [(t.closed_at - t.opened_at).total_seconds() / 3600 for t in trades if t.closed_at]
    return Decimal(str(round(statistics.median(hours), 2))) if hours else None
