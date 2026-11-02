"""Swing points. A swing is unknown until `strength` candles after it (the confirmation delay)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal

from trading_intel.technical_analysis.series import CandleSeries

DEFAULT_STRENGTH: Final = 3

SwingKind = Literal["high", "low"]


@dataclass(frozen=True)
class Swing:
    kind: SwingKind
    index: int
    price: float
    time: datetime
    confirmed_index: int
    confirmed_at: datetime
    label: str | None = None  # HH, LH, HL or LL. None for the first swing of its kind.


def _label(kind: SwingKind, price: float, previous: float | None) -> str | None:
    if previous is None or price == previous:
        return None
    if kind == "high":
        return "HH" if price > previous else "LH"
    return "HL" if price > previous else "LL"


def find_swings(series: CandleSeries, strength: int = DEFAULT_STRENGTH) -> list[Swing]:
    """Confirmed swings in confirmation order. Later candles can never add an earlier one."""
    highs, lows = series.high, series.low
    swings: list[Swing] = []
    previous: dict[SwingKind, float | None] = {"high": None, "low": None}
    for index in range(strength, len(series) - strength):
        before = range(index - strength, index)
        after = range(index + 1, index + strength + 1)
        is_high = all(highs[index] > highs[i] for i in before) and all(
            highs[index] >= highs[i] for i in after
        )
        is_low = all(lows[index] < lows[i] for i in before) and all(
            lows[index] <= lows[i] for i in after
        )
        confirmed = index + strength
        for kind, flag, price in (
            ("high", is_high, float(highs[index])),
            ("low", is_low, float(lows[index])),
        ):
            if flag:
                swing_kind: SwingKind = "high" if kind == "high" else "low"
                swings.append(
                    Swing(
                        kind=swing_kind,
                        index=index,
                        price=price,
                        time=series.close_time[index],
                        confirmed_index=confirmed,
                        confirmed_at=series.close_time[confirmed],
                        label=_label(swing_kind, price, previous[swing_kind]),
                    )
                )
                previous[swing_kind] = price
    return swings
