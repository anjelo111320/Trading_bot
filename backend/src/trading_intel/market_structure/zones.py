"""Supply, demand and consolidation zones. A zone is fixed when detected."""

from typing import Final

import numpy as np

from trading_intel.domain.patterns import DetectedPattern, Direction, clamp_score
from trading_intel.technical_analysis.series import CandleSeries, FloatArray

MAX_BASE_CANDLES: Final = 5
BASE_RANGE_ATR: Final = 1.5
IMPULSE_BODY_ATR: Final = 1.5
CONSOLIDATION_CANDLES: Final = 10
CONSOLIDATION_RANGE_ATR: Final = 3.0


def supply_demand_zones(series: CandleSeries, atr: FloatArray) -> list[DetectedPattern]:
    found: list[DetectedPattern] = []
    for index in range(MAX_BASE_CANDLES + 1, len(series)):
        unit = float(atr[index - 1])
        if np.isnan(unit) or unit <= 0:
            continue
        body = float(series.close[index] - series.open[index])
        if abs(body) < IMPULSE_BODY_ATR * unit:
            continue
        base_high = base_low = None
        size = 0
        for count in range(1, MAX_BASE_CANDLES + 1):
            top = float(series.high[index - count : index].max())
            bottom = float(series.low[index - count : index].min())
            if top - bottom > BASE_RANGE_ATR * unit:
                break
            base_high, base_low, size = top, bottom, count
        if base_high is None or base_low is None:
            continue
        rising = body > 0
        found.append(
            _invalidate_zone(
                series,
                index,
                DetectedPattern(
                    pattern_type="demand_zone" if rising else "supply_zone",
                    direction=Direction.BULLISH if rising else Direction.BEARISH,
                    formed_at=series.close_time[index - size],
                    detected_at=series.close_time[index],
                    zone_low=base_low,
                    zone_high=base_high,
                    strength=clamp_score(abs(body) / unit * 25),
                    evidence={"base_candles": size, "impulse_body_atr": round(abs(body) / unit, 3)},
                ),
            )
        )
    return found


def _invalidate_zone(series: CandleSeries, start: int, pattern: DetectedPattern) -> DetectedPattern:
    assert pattern.zone_low is not None and pattern.zone_high is not None
    for index in range(start + 1, len(series)):
        close = float(series.close[index])
        if (pattern.direction is Direction.BULLISH and close < pattern.zone_low) or (
            pattern.direction is Direction.BEARISH and close > pattern.zone_high
        ):
            return pattern.invalidated(series.close_time[index])
    return pattern


def consolidations(series: CandleSeries, atr: FloatArray) -> list[DetectedPattern]:
    """Fixed to the first ten candles of the run, so later data cannot reshape it."""
    found: list[DetectedPattern] = []
    index = 0
    last = len(series) - CONSOLIDATION_CANDLES
    while index <= last:
        end = index + CONSOLIDATION_CANDLES
        unit = float(atr[index])
        top = float(series.high[index:end].max())
        bottom = float(series.low[index:end].min())
        if np.isnan(unit) or unit <= 0 or top - bottom > CONSOLIDATION_RANGE_ATR * unit:
            index += 1
            continue
        exit_index = _first_close_outside(series, end, bottom, top)
        pattern = DetectedPattern(
            pattern_type="consolidation",
            direction=Direction.NEUTRAL,
            formed_at=series.close_time[index],
            detected_at=series.close_time[end - 1],
            zone_low=bottom,
            zone_high=top,
            strength=clamp_score((1 - (top - bottom) / (CONSOLIDATION_RANGE_ATR * unit)) * 100),
            evidence={"range_atr": round((top - bottom) / unit, 3)},
        )
        if exit_index is None:
            found.append(pattern)
            break
        found.append(pattern.invalidated(series.close_time[exit_index]))
        index = exit_index
    return found


def _first_close_outside(series: CandleSeries, start: int, bottom: float, top: float) -> int | None:
    for index in range(start, len(series)):
        close = float(series.close[index])
        if close > top or close < bottom:
            return index
    return None
