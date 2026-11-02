"""Timeframe roles. Each view uses only candles closed by the decision time."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from trading_intel.domain.candles import ClosedCandle, Timeframe
from trading_intel.market_structure.structure import Trend, analyse_structure
from trading_intel.market_structure.swings import find_swings
from trading_intel.technical_analysis.series import CandleSeries

DEFAULT_ROLES: Final[Mapping[str, Timeframe]] = {
    "direction": Timeframe.D1,
    "structure": Timeframe.H4,
    "intermediate": Timeframe.H1,
    "setup": Timeframe.M15,
    "confirmation": Timeframe.M5,
    "refinement": Timeframe.M1,
}


@dataclass(frozen=True)
class RoleView:
    role: str
    timeframe: Timeframe
    trend: Trend
    candles_used: int


@dataclass(frozen=True)
class MultiTimeframeView:
    decision_time: datetime
    roles: list[RoleView]
    direction: Trend
    alignment: float | None  # Share of other roles agreeing with the direction role.


def build_view(
    candles_by_timeframe: Mapping[Timeframe, Sequence[ClosedCandle]],
    decision_time: datetime,
    roles: Mapping[str, Timeframe] = DEFAULT_ROLES,
) -> MultiTimeframeView:
    views: list[RoleView] = []
    for role, timeframe in roles.items():
        usable = [
            c for c in candles_by_timeframe.get(timeframe, ()) if c.close_time <= decision_time
        ]
        trend: Trend = "none"
        if usable:
            series = CandleSeries.of(usable)
            trend = analyse_structure(series, find_swings(series)).trend[-1]
        views.append(RoleView(role, timeframe, trend, len(usable)))

    direction: Trend = next((v.trend for v in views if v.role == "direction"), "none")
    others = [v for v in views if v.role != "direction"]
    alignment = None
    if direction != "none" and others:
        alignment = sum(v.trend == direction for v in others) / len(others)
    return MultiTimeframeView(decision_time, views, direction, alignment)
