"""BOS and CHoCH, as a state machine over candle closes. A wick never counts."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from trading_intel.domain.patterns import Direction
from trading_intel.market_structure.swings import Swing
from trading_intel.technical_analysis.series import CandleSeries

Trend = Literal["up", "down", "none"]


@dataclass(frozen=True)
class StructureEvent:
    kind: Literal["BOS", "CHOCH"]
    direction: Direction
    index: int
    time: datetime
    level: float
    swing_index: int


@dataclass(frozen=True)
class StructureState:
    events: list[StructureEvent]
    trend: list[Trend]  # One entry per candle.


def analyse_structure(series: CandleSeries, swings: Sequence[Swing]) -> StructureState:
    by_confirmation: dict[int, list[Swing]] = {}
    for swing in swings:
        by_confirmation.setdefault(swing.confirmed_index, []).append(swing)

    trend: Trend = "none"
    trends: list[Trend] = []
    events: list[StructureEvent] = []
    high: Swing | None = None
    low: Swing | None = None
    for index in range(len(series)):
        for swing in by_confirmation.get(index, []):
            if swing.kind == "high":
                high = swing
            else:
                low = swing
        close = float(series.close[index])
        when = series.close_time[index]
        if high is not None and close > high.price:
            kind: Literal["BOS", "CHOCH"] = "CHOCH" if trend == "down" else "BOS"
            events.append(
                StructureEvent(kind, Direction.BULLISH, index, when, high.price, high.index)
            )
            trend, high = "up", None
        elif low is not None and close < low.price:
            kind = "CHOCH" if trend == "up" else "BOS"
            events.append(
                StructureEvent(kind, Direction.BEARISH, index, when, low.price, low.index)
            )
            trend, low = "down", None
        trends.append(trend)
    return StructureState(events, trends)
