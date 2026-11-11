"""When Python asks Claude about an open trade: the docs/37 price checks, at a 15M close.

Plain calculations on closed candles. Earlier reviews of the same trade are the only memory,
so a check fires once per new best, once per target, or once every two hours, and a restart
cannot ask twice.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from statistics import median
from typing import Final

from trading_intel.domain.candles import ClosedCandle
from trading_intel.domain.signals import Side

STALL: Final = "stall past +1R"
REJECTED: Final = "rejected near a target"
VOLATILITY: Final = "volatility jump"
STALL_AGE: Final = timedelta(hours=2)  # 8 15M candles.
VOLATILITY_GAP: Final = timedelta(hours=2)
NEAR_TARGET_R: Final = Decimal("0.25")
REJECTED_R: Final = Decimal("0.5")
VOLATILITY_MULTIPLE: Final = 3
RANGE_WINDOW: Final = 96  # 15M candles in a day.


@dataclass(frozen=True)
class TradeAtClose:
    """An open trade at a 15M close, from the shared simulator's replay."""

    side: Side
    entry: Decimal  # The entry fill.
    risk: Decimal  # Planned risk per unit.
    targets: tuple[Decimal, ...]
    targets_hit: int
    tick: Decimal
    best: Decimal  # The best price after the entry minute.
    best_at: datetime
    close_time: datetime


@dataclass(frozen=True)
class PriorReview:
    checks: tuple[str, ...]
    targets_hit: int
    best_at: datetime | None
    close_time: datetime


def usual_range(quarters: Sequence[ClosedCandle]) -> Decimal | None:
    """The median range of the 96 15M candles before the last one."""
    if len(quarters) <= RANGE_WINDOW:
        return None
    return median(c.high - c.low for c in quarters[-RANGE_WINDOW - 1 : -1])


def fired_checks(
    trade: TradeAtClose,
    quarter: ClosedCandle,
    usual: Decimal | None,
    prior: Sequence[PriorReview],
) -> tuple[str, ...]:
    """The checks that fire on `quarter`, the 15M candle that has just closed."""
    sign, risk = trade.side.sign, trade.risk
    fired: list[str] = []
    stalled = (
        sign * (trade.best - trade.entry) >= risk
        and trade.close_time - trade.best_at >= STALL_AGE
        and all(trade.best_at != r.best_at for r in prior if STALL in r.checks)
    )
    if stalled:
        fired.append(STALL)
    index = trade.targets_hit
    if index < len(trade.targets) and all(
        r.targets_hit != index for r in prior if REJECTED in r.checks
    ):
        target = trade.targets[index]
        extreme = quarter.high if sign > 0 else quarter.low
        near = sign * (target - extreme) <= NEAR_TARGET_R * risk
        through = sign * (extreme - target) >= trade.tick
        back = sign * (extreme - quarter.close) >= REJECTED_R * risk
        if near and not through and back:
            fired.append(REJECTED)
    last = max((r.close_time for r in prior if VOLATILITY in r.checks), default=None)
    jumped = (
        usual is not None
        and usual > 0
        and quarter.high - quarter.low >= VOLATILITY_MULTIPLE * usual
        and (last is None or trade.close_time - last >= VOLATILITY_GAP)
    )
    if jumped:
        fired.append(VOLATILITY)
    return tuple(fired)
