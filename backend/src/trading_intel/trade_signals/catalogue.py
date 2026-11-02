"""Candidate price levels. Python supplies every price, and any AI only selects by ID (D009)."""

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Final, Literal

from trading_intel.domain.candles import Timeframe
from trading_intel.domain.patterns import DetectedPattern
from trading_intel.market_structure.levels import support_resistance
from trading_intel.market_structure.swings import Swing
from trading_intel.pattern_detection.imbalance import fair_value_gaps
from trading_intel.technical_analysis.series import CandleSeries, FloatArray

MAX_LEVELS: Final = 24
RECENT_SWINGS: Final = 6
# Stops sit behind swings, often 2 to 4 ATR away, so 2:1 needs projections beyond 5 ATR.
ATR_PROJECTIONS: Final = (1.5, 3.0, 5.0, 8.0, 12.0)

LevelKind = Literal[
    "swing_high", "swing_low", "support", "resistance", "fvg_edge", "atr_projection"
]


def to_tick(value: float | Decimal, tick: Decimal) -> Decimal:
    """Round to the nearest tick. Float input passes through text, keeping its digits."""
    exact = value if isinstance(value, Decimal) else Decimal(str(value))
    return (exact / tick).to_integral_value(rounding=ROUND_HALF_UP) * tick


@dataclass(frozen=True)
class CatalogueLevel:
    id: str
    kind: LevelKind
    price: Decimal
    timeframe: Timeframe
    position: Literal["above", "below"]
    evidence: str


@dataclass(frozen=True)
class LevelCatalogue:
    as_of: datetime
    close: Decimal
    atr: Decimal
    levels: tuple[CatalogueLevel, ...]

    def resolve(self, level_id: str) -> CatalogueLevel | None:
        return next((level for level in self.levels if level.id == level_id), None)

    def above(self) -> list[CatalogueLevel]:
        return sorted((v for v in self.levels if v.position == "above"), key=lambda v: v.price)

    def below(self) -> list[CatalogueLevel]:
        return sorted(
            (v for v in self.levels if v.position == "below"), key=lambda v: v.price, reverse=True
        )


def _open_gaps(series: CandleSeries, atr: FloatArray) -> list[DetectedPattern]:
    return [p for p in fair_value_gaps(series, atr) if p.invalidated_at is None]


def build_catalogue(
    series: CandleSeries, swings: list[Swing], atr: FloatArray, tick: Decimal
) -> LevelCatalogue | None:
    """Levels known at the last candle, nearest first. None until ATR has warmed up."""
    last = len(series) - 1
    unit = float(atr[last])
    if unit != unit or unit <= 0:
        return None
    close = float(series.close[last])
    raw: list[tuple[LevelKind, float, str]] = []
    for swing in [s for s in swings if s.confirmed_index <= last][-RECENT_SWINGS:]:
        kind: LevelKind = "swing_high" if swing.kind == "high" else "swing_low"
        raw.append((kind, swing.price, f"confirmed {swing.confirmed_at.isoformat()}"))
    for level in support_resistance(series, swings, atr, last):
        raw.append((level.kind, level.price, f"{level.touches} touches"))
    for gap in _open_gaps(series, atr):
        assert gap.zone_low is not None and gap.zone_high is not None
        edge = gap.zone_low if close > gap.zone_high else gap.zone_high
        raw.append(("fvg_edge", edge, f"open {gap.direction.value} gap"))
    for multiple in ATR_PROJECTIONS:
        raw.append(("atr_projection", close + multiple * unit, f"close + {multiple} ATR"))
        raw.append(("atr_projection", close - multiple * unit, f"close - {multiple} ATR"))

    seen: dict[Decimal, tuple[LevelKind, str]] = {}
    for kind, price, evidence in raw:
        rounded = to_tick(price, tick)
        if rounded > 0 and rounded != to_tick(close, tick):
            seen.setdefault(rounded, (kind, evidence))
    ordered = sorted(seen.items(), key=lambda item: abs(float(item[0]) - close))[:MAX_LEVELS]
    levels = tuple(
        CatalogueLevel(
            id=f"L{index}",
            kind=kind,
            price=price,
            timeframe=series.timeframe,
            position="above" if float(price) > close else "below",
            evidence=evidence,
        )
        for index, (price, (kind, evidence)) in enumerate(ordered, start=1)
    )
    return LevelCatalogue(
        as_of=series.close_time[last],
        close=to_tick(close, tick),
        atr=Decimal(str(unit)),
        levels=levels,
    )
