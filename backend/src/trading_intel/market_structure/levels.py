"""Support and resistance from clustered swings, as known at one candle."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal

from trading_intel.market_structure.swings import Swing
from trading_intel.technical_analysis.series import CandleSeries, FloatArray

CLUSTER_ATR: Final = 0.5
MIN_TOUCHES: Final = 2
SCORE_PER_TOUCH: Final = 25.0


@dataclass(frozen=True)
class Level:
    kind: Literal["support", "resistance"]
    price: float
    touches: int
    first_touch: datetime
    last_touch: datetime
    strength: float


def support_resistance(
    series: CandleSeries, swings: Sequence[Swing], atr: FloatArray, as_of: int
) -> list[Level]:
    """Levels from swings confirmed by candle `as_of`, nearest to the close first."""
    tolerance = float(atr[as_of]) * CLUSTER_ATR
    if tolerance != tolerance:  # NaN during warm-up.
        return []
    known = sorted((s for s in swings if s.confirmed_index <= as_of), key=lambda s: s.price)
    clusters: list[list[Swing]] = []
    for swing in known:
        if clusters:
            members = clusters[-1]
            mean = sum(item.price for item in members) / len(members)
            if abs(swing.price - mean) <= tolerance:
                members.append(swing)
                continue
        clusters.append([swing])

    close = float(series.close[as_of])
    levels: list[Level] = []
    for members in clusters:
        if len(members) < MIN_TOUCHES:
            continue
        price = sum(item.price for item in members) / len(members)
        levels.append(
            Level(
                kind="resistance" if price >= close else "support",
                price=price,
                touches=len(members),
                first_touch=min(item.time for item in members),
                last_touch=max(item.time for item in members),
                strength=min(SCORE_PER_TOUCH * len(members), 100.0),
            )
        )
    return sorted(levels, key=lambda level: abs(level.price - close))
