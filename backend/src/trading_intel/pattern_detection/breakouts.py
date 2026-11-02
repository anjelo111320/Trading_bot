"""Breakouts confirmed by volume, and those that fail."""

from collections.abc import Sequence
from typing import Final

import numpy as np

from trading_intel.domain.patterns import DetectedPattern, Direction, clamp_score
from trading_intel.market_structure.structure import StructureEvent
from trading_intel.technical_analysis.series import CandleSeries, FloatArray

MIN_RELATIVE_VOLUME: Final = 1.5
FALSE_BREAKOUT_CANDLES: Final = 3


def breakouts(
    series: CandleSeries, events: Sequence[StructureEvent], relative_volume: FloatArray
) -> list[DetectedPattern]:
    found: list[DetectedPattern] = []
    for event in events:
        ratio = float(relative_volume[event.index])
        if np.isnan(ratio) or ratio < MIN_RELATIVE_VOLUME:
            continue
        rising = event.direction is Direction.BULLISH
        breakout = DetectedPattern(
            pattern_type="breakout",
            direction=event.direction,
            formed_at=event.time,
            detected_at=event.time,
            price_level=event.level,
            strength=clamp_score(ratio / 3 * 100),
            evidence={"relative_volume": round(ratio, 3), "structure": event.kind},
        )
        last = min(event.index + FALSE_BREAKOUT_CANDLES, len(series) - 1)
        for index in range(event.index + 1, last + 1):
            close = float(series.close[index])
            if (rising and close < event.level) or (not rising and close > event.level):
                breakout = breakout.invalidated(series.close_time[index])
                found.append(
                    DetectedPattern(
                        pattern_type="false_breakout",
                        direction=Direction.BEARISH if rising else Direction.BULLISH,
                        formed_at=event.time,
                        detected_at=series.close_time[index],
                        price_level=event.level,
                        strength=clamp_score(ratio / 3 * 100),
                        evidence={"candles_to_failure": index - event.index},
                    )
                )
                break
        found.append(breakout)
    return found
