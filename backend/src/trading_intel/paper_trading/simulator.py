"""The shared execution simulator, driven by closed 1M candles.

Backtests and paper trading both use this file, so paper results really do validate
backtests. Rules are in docs/10-BACKTESTING.md. Whenever a candle is ambiguous, the
outcome that is worse for the trade is assumed. Limits fill only on a trade-through.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_FLOOR, Decimal
from enum import StrEnum
from typing import Final, Literal

from trading_intel.domain.candles import ClosedCandle
from trading_intel.domain.signals import EntryType, Side

ZERO: Final = Decimal(0)
LIQUIDITY_CAP: Final = Decimal("0.05")

FillKind = Literal["entry", "tp1", "tp2", "tp3", "stop", "invalidation", "expiry", "funding"]


class OrderStatus(StrEnum):
    PENDING = "pending"
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class SimulatedOrder:
    side: Side
    entry_type: EntryType
    entry: Decimal
    stop: Decimal
    targets: tuple[Decimal, ...]
    allocation: tuple[Decimal, ...]
    quantity: Decimal
    tick: Decimal
    lot_step: Decimal
    taker_fee: Decimal
    maker_fee: Decimal
    half_spread: Decimal
    entry_slippage: Decimal
    stop_slippage: Decimal
    placed_at: datetime
    expires_at: datetime
    liquidity_cap: Decimal = LIQUIDITY_CAP
    # A market entry already taken at `placed_at` from the live book, costs included (D044).
    # It fills inside the minute it was placed, where only the stop is checked, because part
    # of that minute traded before the entry.
    filled_price: Decimal | None = None


@dataclass(frozen=True)
class Fill:
    kind: FillKind
    at: datetime
    quantity: Decimal = ZERO
    price: Decimal | None = None
    fee: Decimal = ZERO
    spread_cost: Decimal = ZERO
    slippage_cost: Decimal = ZERO
    funding: Decimal = ZERO


@dataclass
class TradeSimulator:
    order: SimulatedOrder
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: Decimal = ZERO
    open_quantity: Decimal = ZERO
    entry_fill: Decimal | None = None
    next_target: int = 0
    fills: list[Fill] = field(default_factory=list)
    stop: Decimal = field(init=False)

    def __post_init__(self) -> None:
        self.stop = self.order.stop

    def move_stop(self, level: Decimal) -> bool:
        """Tighten the stop for later candles. A stop never moves against the trade."""
        if self.status is not OrderStatus.OPEN or self.order.side.sign * (level - self.stop) <= 0:
            return False
        self.stop = level
        return True

    @property
    def is_finished(self) -> bool:
        return self.status in (OrderStatus.CLOSED, OrderStatus.CANCELLED)

    def on_candle(self, candle: ClosedCandle) -> list[Fill]:
        if self.is_finished or not self._reaches(candle):
            return []
        start = len(self.fills)
        pending = self.status is OrderStatus.PENDING
        if pending:
            self._try_entry(candle)
        if self.status is OrderStatus.OPEN:
            # A limit fills on a move against the trade, and a target in the same candle may
            # have traded before it. Only the stop counts in that candle (docs/10).
            limit_filled = pending and self.order.entry_type is EntryType.LIMIT
            early = candle.open_time < self.order.placed_at
            self._try_exits(candle, stop_only=limit_filled or early)
        return self.fills[start:]

    def _reaches(self, candle: ClosedCandle) -> bool:
        """A taken entry starts in the minute it was placed, and any other order after it."""
        if self.order.filled_price is not None:
            return candle.close_time > self.order.placed_at
        return candle.open_time >= self.order.placed_at

    def on_funding(self, at: datetime, rate: Decimal, mark: Decimal) -> list[Fill]:
        """Longs pay a positive rate, and shorts receive it."""
        if self.status is not OrderStatus.OPEN or at < self.order.placed_at:
            return []
        cash = -self.order.side.sign * rate * mark * self.open_quantity
        fill = Fill("funding", at, quantity=self.open_quantity, funding=cash)
        self.fills.append(fill)
        return [fill]

    def _try_entry(self, candle: ClosedCandle) -> None:
        order = self.order
        if candle.open_time >= order.expires_at:
            self._cancel("expiry", candle.open_time)
            return
        price = self._entry_price(candle)
        if price is None:
            if self._invalidated_before_entry(candle):
                self._cancel("invalidation", candle.close_time)
            return
        allowed = self._floor(candle.volume * order.liquidity_cap)
        quantity = min(order.quantity, allowed)
        if quantity <= 0 and order.filled_price is not None:
            self._cancel("expiry", candle.close_time)  # The live price is gone after its minute.
            return
        if quantity <= 0:
            return  # Nothing traded, so the order stays open.
        is_limit = order.entry_type is EntryType.LIMIT
        half = ZERO if is_limit else order.half_spread
        slip = ZERO if is_limit else order.entry_slippage
        rate = order.maker_fee if is_limit else order.taker_fee
        self.entry_fill = price
        self.filled_quantity = self.open_quantity = quantity
        self.status = OrderStatus.OPEN
        self.fills.append(
            Fill(
                "entry",
                max(candle.open_time, order.placed_at),
                quantity,
                price,
                fee=rate * price * quantity,
                spread_cost=half * quantity,
                slippage_cost=slip * quantity,
            )
        )

    def _entry_price(self, candle: ClosedCandle) -> Decimal | None:
        order, sign = self.order, self.order.side.sign
        if order.filled_price is not None:
            return order.filled_price
        costs = order.half_spread + order.entry_slippage
        match order.entry_type:
            case EntryType.MARKET:
                return candle.open + sign * costs
            case EntryType.STOP:
                beyond = candle.high > order.entry if sign > 0 else candle.low < order.entry
                if not beyond:
                    return None
                worse = max(order.entry, candle.open) if sign > 0 else min(order.entry, candle.open)
                return worse + sign * costs
            case EntryType.LIMIT:
                through = (
                    candle.low <= order.entry - order.tick
                    if sign > 0
                    else candle.high >= order.entry + order.tick
                )
                return order.entry if through else None
        return None

    def _invalidated_before_entry(self, candle: ClosedCandle) -> bool:
        return self.order.side.sign * (candle.close - self.stop) <= 0

    def _cancel(self, kind: FillKind, at: datetime) -> None:
        self.status = OrderStatus.CANCELLED
        self.fills.append(Fill(kind, at))

    def _try_exits(self, candle: ClosedCandle, *, stop_only: bool = False) -> None:
        """The stop is checked first, so a candle reaching both counts as a loss."""
        order, sign = self.order, self.order.side.sign
        stopped = candle.low <= self.stop if sign > 0 else candle.high >= self.stop
        if stopped:
            worse = min(self.stop, candle.open) if sign > 0 else max(self.stop, candle.open)
            price = worse - sign * (order.half_spread + order.stop_slippage)
            self._exit("stop", candle, self.open_quantity, price, order.taker_fee, True)
            return
        if stop_only:
            return
        while self.next_target < len(order.targets):
            target = order.targets[self.next_target]
            through = (
                candle.high >= target + order.tick
                if sign > 0
                else candle.low <= target - order.tick
            )
            if not through:
                return
            is_last = self.next_target == len(order.targets) - 1
            share = self._floor(self.filled_quantity * order.allocation[self.next_target])
            quantity = self.open_quantity if is_last else min(share, self.open_quantity)
            kinds: tuple[FillKind, ...] = ("tp1", "tp2", "tp3")
            self._exit(kinds[self.next_target], candle, quantity, target, order.maker_fee, False)
            self.next_target += 1
            if self.status is OrderStatus.CLOSED:
                return

    def _exit(
        self,
        kind: FillKind,
        candle: ClosedCandle,
        quantity: Decimal,
        price: Decimal,
        rate: Decimal,
        pays_costs: bool,
    ) -> None:
        order = self.order
        self.open_quantity -= quantity
        if self.open_quantity <= 0:
            self.status = OrderStatus.CLOSED
        self.fills.append(
            Fill(
                kind,
                candle.close_time,
                quantity,
                price,
                fee=rate * price * quantity,
                spread_cost=order.half_spread * quantity if pays_costs else ZERO,
                slippage_cost=order.stop_slippage * quantity if pays_costs else ZERO,
            )
        )

    def _floor(self, quantity: Decimal) -> Decimal:
        step = self.order.lot_step
        return (quantity / step).to_integral_value(rounding=ROUND_FLOOR) * step


@dataclass(frozen=True)
class TradeResult:
    entered: bool
    gross_pnl: Decimal
    fees: Decimal
    spread_cost: Decimal
    slippage_cost: Decimal
    funding: Decimal
    net_pnl: Decimal
    exit_reason: str
    entry_price: Decimal | None
    exit_price: Decimal | None
    entry_time: datetime | None
    exit_time: datetime | None
    quantity: Decimal


def summarise(side: Side, fills: Sequence[Fill]) -> TradeResult:
    """Spread and slippage are already inside fill prices, and are shown only for reporting."""
    entry = next((f for f in fills if f.kind == "entry"), None)
    exits = [f for f in fills if f.kind in ("tp1", "tp2", "tp3", "stop")]
    gross = ZERO
    if entry is not None and entry.price is not None:
        for fill in exits:
            assert fill.price is not None
            gross += side.sign * (fill.price - entry.price) * fill.quantity
    fees = sum((f.fee for f in fills), ZERO)
    funding = sum((f.funding for f in fills), ZERO)
    last = exits[-1] if exits else None
    closing = [f for f in fills if f.kind in ("expiry", "invalidation")]
    reason = last.kind if last else (closing[-1].kind if closing else "open")
    return TradeResult(
        entered=entry is not None,
        gross_pnl=gross,
        fees=fees,
        spread_cost=sum((f.spread_cost for f in fills), ZERO),
        slippage_cost=sum((f.slippage_cost for f in fills), ZERO),
        funding=funding,
        net_pnl=gross - fees + funding,
        exit_reason=reason,
        entry_price=entry.price if entry else None,
        exit_price=last.price if last else None,
        entry_time=entry.at if entry else None,
        exit_time=last.at if last else None,
        quantity=entry.quantity if entry else ZERO,
    )
