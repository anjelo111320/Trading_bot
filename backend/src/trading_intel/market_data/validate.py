"""Checks that need context beyond the candle itself. Pure: same input, same output.

A candle's own invariants are enforced when it is built. Data is never filled or
adjusted here, and a rejection always carries a reason.
"""

from datetime import datetime, timedelta

from trading_intel.domain.candles import ClosedCandle

CLOCK_TOLERANCE = timedelta(seconds=5)


def rejection_reason(candle: ClosedCandle, now: datetime) -> str | None:
    """Return why a closed candle must be refused, or None if it is acceptable."""
    if candle.close_time > now + CLOCK_TOLERANCE:
        return "close_time_in_future"
    return None
