"""Exit rules tried on a strategy's own entries, and the checks an AI exit manager would get.

Both come from docs/37. A rule decides at a setup-candle close, from candles closed by then,
and acts from the next fill candle: a tighter stop, or a market exit at that candle's open.
`replay` runs one trade through the shared simulator, so with no rule it must give exactly
what the backtest engine gave.
"""

from bisect import bisect_left, bisect_right
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from statistics import median
from typing import Final, Literal, Protocol

from trading_intel.backtesting.engine import FundingEvent, TrailingStop
from trading_intel.domain.candles import ClosedCandle
from trading_intel.domain.signals import Side
from trading_intel.market_structure.swings import Swing
from trading_intel.paper_trading.simulator import (
    OrderStatus,
    SimulatedOrder,
    TradeResult,
    TradeSimulator,
    summarise,
)
from trading_intel.trade_signals.catalogue import to_tick

EXIT: Final = "exit"
RANGE_WINDOW: Final = 96  # 15M candles in a day, for the volatility check.

Action = Decimal | Literal["exit"] | None


@dataclass(frozen=True)
class OpenTrade:
    """What a rule sees of an open trade at a setup close."""

    side: Side
    entry: Decimal  # The entry fill, costs included.
    risk: Decimal  # Planned risk per unit: the planned entry to the first stop.
    stop: Decimal
    breakeven: Decimal  # The stop that nets about zero after costs.
    best: Decimal | None  # The best price after the entry candle, None before one closes.
    stale: int  # Setup closes since `best` last improved.
    close: Decimal  # This setup candle's close.
    targets_hit: int
    moment: datetime

    def progress(self, price: Decimal) -> Decimal:
        """How far `price` is beyond the entry fill, in R."""
        return self.side.sign * (price - self.entry) / self.risk

    @property
    def reached_one_r(self) -> bool:
        return self.best is not None and self.progress(self.best) >= 1


class ExitRule(Protocol):
    @property
    def name(self) -> str: ...

    def decide(self, trade: OpenTrade) -> Action: ...


@dataclass(frozen=True)
class Breakeven:
    """After +1R, the stop goes to where a stop-out nets about zero."""

    name: str = "breakeven"

    def decide(self, trade: OpenTrade) -> Action:
        return trade.breakeven if trade.reached_one_r else None


@dataclass(frozen=True)
class StallExit:
    """Take the profit when a trade in profit has stopped making progress, before any target."""

    name: str = "stall_exit"
    min_progress: Decimal = Decimal("0.5")
    stale_closes: int = 6

    def decide(self, trade: OpenTrade) -> Action:
        stalled = trade.best is not None and trade.stale >= self.stale_closes
        in_profit = trade.progress(trade.close) >= self.min_progress
        return EXIT if trade.targets_hit == 0 and stalled and in_profit else None


class SwingTrail:
    """After +1R, the stop follows the latest confirmed setup swing against the trade."""

    name: Final = "swing_trail"

    def __init__(self, swings: Sequence[Swing], tick: Decimal) -> None:
        self._tick = tick
        self._lows = [s for s in swings if s.kind == "low"]
        self._highs = [s for s in swings if s.kind == "high"]
        self._low_times = [s.confirmed_at for s in self._lows]
        self._high_times = [s.confirmed_at for s in self._highs]

    def decide(self, trade: OpenTrade) -> Action:
        if not trade.reached_one_r:
            return None
        long = trade.side is Side.LONG
        swings, times = (self._lows, self._low_times) if long else (self._highs, self._high_times)
        known = bisect_right(times, trade.moment)
        return to_tick(swings[known - 1].price, self._tick) if known else None


def breakeven_stop(order: SimulatedOrder, entry: Decimal) -> Decimal:
    """The entry fill plus the exit's spread and slippage and both taker fees, rounded away."""
    sign = order.side.sign
    level = entry + sign * (order.half_spread + order.stop_slippage + 2 * order.taker_fee * entry)
    rounding = ROUND_CEILING if sign > 0 else ROUND_FLOOR
    return (level / order.tick).to_integral_value(rounding=rounding) * order.tick


def prior_median_ranges(candles: Sequence[ClosedCandle]) -> dict[datetime, Decimal]:
    """Each candle's close time, with the median range of the candles before it."""
    ranges = [c.high - c.low for c in candles]
    return {
        candles[index].close_time: median(ranges[index - RANGE_WINDOW : index])
        for index in range(RANGE_WINDOW, len(candles))
    }


@dataclass
class CheckCounts:
    """How often an AI exit manager would have been asked, summed over trades (docs/37)."""

    open_candles: int = 0
    trades: int = 0
    checks: Counter[str] = field(default_factory=Counter)

    @property
    def total(self) -> int:
        return sum(self.checks.values())


class TradeChecks:
    """One trade's checks, at each 15M close after the entry candle while it is open."""

    STALL_CANDLES: Final = 8
    NEAR_TARGET_R: Final = Decimal("0.25")
    REJECTED_R: Final = Decimal("0.5")
    VOLATILITY_MULTIPLE: Final = 3
    VOLATILITY_GAP: Final = 8

    def __init__(self, counts: CheckCounts, medians: Mapping[datetime, Decimal]) -> None:
        self._counts = counts
        self._medians = medians
        self._stale = 0
        self._stall_armed = True
        self._flagged_targets: set[int] = set()
        self._since_volatility = self.VOLATILITY_GAP
        counts.trades += 1

    def on_close(
        self, simulator: TradeSimulator, candle: ClosedCandle, best: Decimal, improved: bool
    ) -> None:
        order, counts = simulator.order, self._counts
        assert simulator.entry_fill is not None
        sign, risk = order.side.sign, abs(order.entry - order.stop)
        counts.open_candles += 1
        if improved:
            self._stale, self._stall_armed = 0, True
        else:
            self._stale += 1
        if (
            self._stall_armed
            and self._stale >= self.STALL_CANDLES
            and sign * (best - simulator.entry_fill) >= risk
        ):
            counts.checks["stall past +1R"] += 1
            self._stall_armed = False
        index = simulator.next_target
        if index < len(order.targets) and index not in self._flagged_targets:
            target = order.targets[index]
            extreme = candle.high if sign > 0 else candle.low
            near = sign * (target - extreme) <= self.NEAR_TARGET_R * risk
            through = sign * (extreme - target) >= order.tick
            back = sign * (extreme - candle.close) >= self.REJECTED_R * risk
            if near and not through and back:
                counts.checks["rejected near a target"] += 1
                self._flagged_targets.add(index)
        self._since_volatility += 1
        usual = self._medians.get(candle.close_time)
        if (
            usual is not None
            and usual > 0
            and self._since_volatility >= self.VOLATILITY_GAP
            and candle.high - candle.low >= self.VOLATILITY_MULTIPLE * usual
        ):
            counts.checks["volatility jump"] += 1
            self._since_volatility = 0


@dataclass(frozen=True)
class Replayed:
    result: TradeResult
    acted: bool  # The rule moved the stop or closed the trade at least once.


def replay(
    order: SimulatedOrder,
    signal_time: datetime,
    fills: Sequence[ClosedCandle],
    open_times: Sequence[datetime],
    setup_closes: Mapping[datetime, Decimal],
    funding: Sequence[FundingEvent],
    end: datetime,
    *,
    trail: TrailingStop | None = None,
    rule: ExitRule | None = None,
    checks: TradeChecks | None = None,
) -> Replayed:
    """One trade, as `BacktestEngine._simulate` runs it, with an optional rule added.

    `open_times` are the fill candles' open times, for finding where the trade starts.
    """
    simulator = TradeSimulator(order)
    sign = order.side.sign
    pending = [event for event in funding if event.at >= signal_time]
    best: Decimal | None = None
    improved = False  # Since the last setup close.
    stale = 0
    acted = False
    for candle in fills[bisect_left(open_times, order.placed_at) :]:
        if candle.open_time >= end:
            break
        while pending and pending[0].at < candle.close_time:
            event = pending.pop(0)
            simulator.on_funding(event.at, event.rate, event.mark)
        was_open = simulator.status is OrderStatus.OPEN
        simulator.on_candle(candle)
        if simulator.is_finished:
            break
        if was_open:
            # The entry candle is left out: part of it may have traded before the entry.
            extreme = candle.high if sign > 0 else candle.low
            better = best is None or sign * (extreme - best) > 0
            if better:
                best, improved = extreme, True
            if checks is not None and best is not None:
                checks.on_close(simulator, candle, best, better)
        close = setup_closes.get(candle.close_time)
        if close is None:
            continue
        if improved:
            stale, improved = 0, False
        elif best is not None:
            stale += 1
        if trail is not None:
            level = trail(candle.close_time, order.side, simulator.stop)
            if level is not None:
                simulator.move_stop(level)  # Effective from the next candle.
        if rule is None or simulator.status is not OrderStatus.OPEN:
            continue
        assert simulator.entry_fill is not None
        action = rule.decide(
            OpenTrade(
                side=order.side,
                entry=simulator.entry_fill,
                risk=abs(order.entry - order.stop),
                stop=simulator.stop,
                breakeven=breakeven_stop(order, simulator.entry_fill),
                best=best,
                stale=stale,
                close=close,
                targets_hit=simulator.next_target,
                moment=candle.close_time,
            )
        )
        if action == EXIT:
            acted = simulator.request_exit() or acted
        elif isinstance(action, Decimal):
            acted = simulator.move_stop(action) or acted
    return Replayed(summarise(order.side, simulator.fills), acted)
