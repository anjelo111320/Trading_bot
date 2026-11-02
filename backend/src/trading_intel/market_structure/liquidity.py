"""Equal highs and lows, and liquidity sweeps."""

from collections.abc import Sequence
from itertools import pairwise
from typing import Final

import numpy as np

from trading_intel.domain.patterns import DetectedPattern, Direction, clamp_score
from trading_intel.market_structure.swings import Swing
from trading_intel.technical_analysis.series import CandleSeries, FloatArray

EQUAL_ATR: Final = 0.1


def equal_levels(
    series: CandleSeries, swings: Sequence[Swing], atr: FloatArray
) -> list[DetectedPattern]:
    found: list[DetectedPattern] = []
    for kind, name, direction in (
        ("high", "equal_highs", Direction.BEARISH),
        ("low", "equal_lows", Direction.BULLISH),
    ):
        same = [s for s in swings if s.kind == kind]
        for first, second in pairwise(same):
            unit = float(atr[second.confirmed_index])
            if np.isnan(unit) or abs(first.price - second.price) > EQUAL_ATR * unit:
                continue
            found.append(
                DetectedPattern(
                    pattern_type=name,
                    direction=direction,
                    formed_at=first.time,
                    detected_at=second.confirmed_at,
                    price_level=max(first.price, second.price)
                    if kind == "high"
                    else min(first.price, second.price),
                    strength=50.0,
                    evidence={"first": first.price, "second": second.price},
                )
            )
    return found


def liquidity_sweeps(series: CandleSeries, swings: Sequence[Swing]) -> list[DetectedPattern]:
    """A wick beyond a confirmed swing, closing back inside on the same candle."""
    by_confirmation: dict[int, list[Swing]] = {}
    for swing in swings:
        by_confirmation.setdefault(swing.confirmed_index, []).append(swing)
    high: Swing | None = None
    low: Swing | None = None
    found: list[DetectedPattern] = []
    for index in range(len(series)):
        close = float(series.close[index])
        if high is not None and float(series.high[index]) > high.price:
            if close < high.price:
                found.append(_sweep(series, index, high, Direction.BEARISH))
            high = None
        if low is not None and float(series.low[index]) < low.price:
            if close > low.price:
                found.append(_sweep(series, index, low, Direction.BULLISH))
            low = None
        for swing in by_confirmation.get(index, []):
            if swing.kind == "high":
                high = swing
            else:
                low = swing
    return found


def _sweep(series: CandleSeries, index: int, swing: Swing, direction: Direction) -> DetectedPattern:
    candle_range = float(series.high[index] - series.low[index])
    reach = (
        float(series.high[index]) - swing.price
        if direction is Direction.BEARISH
        else swing.price - float(series.low[index])
    )
    return DetectedPattern(
        pattern_type="liquidity_sweep",
        direction=direction,
        formed_at=series.close_time[index],
        detected_at=series.close_time[index],
        price_level=swing.price,
        strength=clamp_score(reach / candle_range * 100 if candle_range else 0),
        evidence={"swing_time": swing.time.isoformat()},
    )
