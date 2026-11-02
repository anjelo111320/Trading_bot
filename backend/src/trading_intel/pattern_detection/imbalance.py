"""Fair value gaps and order blocks."""

from collections.abc import Sequence
from typing import Final

import numpy as np

from trading_intel.domain.patterns import DetectedPattern, Direction, clamp_score
from trading_intel.market_structure.structure import StructureEvent
from trading_intel.technical_analysis.series import CandleSeries, FloatArray

ORDER_BLOCK_LOOKBACK: Final = 10


def fair_value_gaps(series: CandleSeries, atr: FloatArray) -> list[DetectedPattern]:
    found: list[DetectedPattern] = []
    for index in range(2, len(series)):
        first_high = float(series.high[index - 2])
        first_low = float(series.low[index - 2])
        third_high = float(series.high[index])
        third_low = float(series.low[index])
        if third_low > first_high:
            direction, low, high = Direction.BULLISH, first_high, third_low
        elif third_high < first_low:
            direction, low, high = Direction.BEARISH, third_high, first_low
        else:
            continue
        unit = float(atr[index])
        score = (high - low) / unit * 50 if not np.isnan(unit) and unit > 0 else 0.0
        pattern = DetectedPattern(
            pattern_type="fair_value_gap",
            direction=direction,
            formed_at=series.close_time[index - 1],
            detected_at=series.close_time[index],
            zone_low=low,
            zone_high=high,
            strength=clamp_score(score),
            evidence={"gap": high - low},
        )
        for later in range(index + 1, len(series)):
            filled = (
                float(series.low[later]) <= low
                if direction is Direction.BULLISH
                else float(series.high[later]) >= high
            )
            if filled:
                pattern = pattern.invalidated(series.close_time[later])
                break
        found.append(pattern)
    return found


def order_blocks(
    series: CandleSeries, events: Sequence[StructureEvent], atr: FloatArray
) -> list[DetectedPattern]:
    """The last opposite-colour candle before a break of structure."""
    found: list[DetectedPattern] = []
    for event in events:
        if event.kind != "BOS":
            continue
        rising = event.direction is Direction.BULLISH
        for index in range(event.index - 1, max(event.index - ORDER_BLOCK_LOOKBACK - 1, -1), -1):
            bearish_candle = series.close[index] < series.open[index]
            if bearish_candle != rising:
                continue
            low, high = float(series.low[index]), float(series.high[index])
            unit = float(atr[event.index])
            pattern = DetectedPattern(
                pattern_type="order_block",
                direction=event.direction,
                formed_at=series.close_time[index],
                detected_at=event.time,
                zone_low=low,
                zone_high=high,
                strength=clamp_score(
                    abs(float(series.close[event.index]) - event.level) / unit * 100
                    if not np.isnan(unit) and unit > 0
                    else 0.0
                ),
                evidence={"bos_level": event.level},
            )
            for later in range(event.index + 1, len(series)):
                close = float(series.close[later])
                if (rising and close < low) or (not rising and close > high):
                    pattern = pattern.invalidated(series.close_time[later])
                    break
            found.append(pattern)
            break
    return found
