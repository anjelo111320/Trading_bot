"""ATR zigzag pivots, the turning points chart patterns are drawn on.

A pivot is unknown until price has moved `reversal_atr` ATR away from it, so `confirmed_at`
is the close of the candle that completed that move. The candle that sets a new extreme
never confirms a reversal itself, because the order of its high and low is unknown.
"""

from typing import Final

from trading_intel.market_structure.swings import Swing, SwingKind
from trading_intel.technical_analysis.series import CandleSeries, FloatArray

DEFAULT_REVERSAL_ATR: Final = 2.5


def _label(kind: SwingKind, price: float, previous: float | None) -> str | None:
    if previous is None or price == previous:
        return None
    if kind == "high":
        return "HH" if price > previous else "LH"
    return "HL" if price > previous else "LL"


class _Builder:
    def __init__(self, series: CandleSeries) -> None:
        self.series = series
        self.pivots: list[Swing] = []
        self.previous: dict[SwingKind, float | None] = {"high": None, "low": None}

    def add(self, kind: SwingKind, index: int, confirmed: int) -> None:
        source = self.series.high if kind == "high" else self.series.low
        price = float(source[index])
        self.pivots.append(
            Swing(
                kind=kind,
                index=index,
                price=price,
                time=self.series.close_time[index],
                confirmed_index=confirmed,
                confirmed_at=self.series.close_time[confirmed],
                label=_label(kind, price, self.previous[kind]),
            )
        )
        self.previous[kind] = price


def _lowest(series: CandleSeries, start: int, end: int) -> int:
    """Index of the lowest low in [start, end], the earliest on ties."""
    return min(range(start, end + 1), key=lambda i: (float(series.low[i]), i))


def _highest(series: CandleSeries, start: int, end: int) -> int:
    return min(range(start, end + 1), key=lambda i: (-float(series.high[i]), i))


def zigzag(
    series: CandleSeries, atr: FloatArray, reversal_atr: float = DEFAULT_REVERSAL_ATR
) -> list[Swing]:
    """Alternating confirmed pivots in confirmation order. Later candles never add earlier ones.

    The threshold uses ATR on the confirming candle. No pivot confirms during ATR warm-up.
    """
    high, low = series.high, series.low
    builder = _Builder(series)
    leg = 0  # 1 while tracking a high, -1 while tracking a low, 0 before the first pivot.
    top = bottom = extreme = 0
    for index in range(1, len(series)):
        unit = float(atr[index])
        threshold = reversal_atr * unit if unit == unit else float("nan")
        if leg == 0:
            new_top, new_bottom = high[index] > high[top], low[index] < low[bottom]
            falls = not new_top and float(high[top] - low[index]) >= threshold
            rises = not new_bottom and float(high[index] - low[bottom]) >= threshold
            if falls and (not rises or top < bottom):
                builder.add("high", top, index)
                leg, extreme = -1, _lowest(series, top + 1, index)
            elif rises:
                builder.add("low", bottom, index)
                leg, extreme = 1, _highest(series, bottom + 1, index)
            else:
                top = index if new_top else top
                bottom = index if new_bottom else bottom
        elif leg == 1:
            if high[index] > high[extreme]:
                extreme = index
            elif float(high[extreme] - low[index]) >= threshold:
                builder.add("high", extreme, index)
                leg, extreme = -1, _lowest(series, extreme + 1, index)
        elif low[index] < low[extreme]:
            extreme = index
        elif float(high[index] - low[extreme]) >= threshold:
            builder.add("low", extreme, index)
            leg, extreme = 1, _highest(series, extreme + 1, index)
    return builder.pivots
