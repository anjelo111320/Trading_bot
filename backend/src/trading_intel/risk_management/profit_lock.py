"""The profit lock on the bot's Binance trades (D066). Pure and deterministic.

Once the mark price has gone 1.5 times a trade's planned risk beyond its entry, the stop moves
to 1 time that risk beyond the entry, so a trade that got that far can no longer end in a loss
at its stop. R is the planned risk per unit, as in every report: the planned entry to the first
stop. The stop only ever tightens, and never to where it would trigger at once.

The owner chose this on 2026-11-14, with no backtest first. The nearest rule tested, breakeven
at +1R (docs/37), changed results by -0.073R to -0.005R a trade on the three strategies tested.
"""

from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Final

from trading_intel.domain.signals import Side

TRIGGER_R: Final = Decimal("1.5")
LOCK_R: Final = Decimal(1)


def lock_level(side: Side, entry: Decimal, risk: Decimal, tick: Decimal) -> Decimal:
    """1R beyond the entry, rounded to the tick that keeps a little less of the profit."""
    level = entry + side.sign * LOCK_R * risk
    rounding = ROUND_FLOOR if side.sign > 0 else ROUND_CEILING
    return (level / tick).to_integral_value(rounding=rounding) * tick


def profit_lock(
    side: Side, entry: Decimal, risk: Decimal, mark: Decimal, stop: Decimal, tick: Decimal
) -> Decimal | None:
    """The stop to move to now, or None: the trade has not reached +1.5R, or its stop is at the
    lock or tighter already. `entry` is the fill, `mark` the price Binance's stop watches and
    `stop` the stop the trade holds now."""
    if min(entry, risk, mark, tick) <= 0:
        return None
    sign = side.sign
    if sign * (mark - entry) < TRIGGER_R * risk:
        return None
    level = lock_level(side, entry, risk, tick)
    if sign * (level - stop) <= 0 or sign * (mark - level) <= 0:
        return None
    return level
