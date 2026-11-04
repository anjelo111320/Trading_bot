"""Numbers that describe a chart pattern's shape, so it can be judged without a picture.

Claude receives these instead of chart images (D035). Distances are in ATR on the breakout
candle, so patterns compare across prices and volatility, and only candles up to the
breakout are read. Each value is a measurement, never a prediction.
"""

from bisect import bisect_left
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Final

from trading_intel.domain.patterns import DetectedPattern, Direction
from trading_intel.technical_analysis.series import CandleSeries, FloatArray

VOLUME_LOOKBACK: Final = 20
CHANNELS: Final = frozenset(
    {
        "rectangle",
        "ascending_triangle",
        "descending_triangle",
        "symmetrical_triangle",
        "rising_wedge",
        "falling_wedge",
        "broadening",
    }
)

Point = tuple[int, float]


def _index(series: CandleSeries, moment: datetime) -> int | None:
    position = bisect_left(series.close_time, moment)
    if position < len(series) and series.close_time[position] == moment:
        return position
    return None


def _points(series: CandleSeries, raw: object) -> list[Point] | None:
    assert isinstance(raw, list)
    found: list[Point] = []
    for when, price in raw:
        position = _index(series, datetime.fromisoformat(when))
        if position is None:
            return None
        found.append((position, float(price)))
    return found


def _r(value: float, digits: int = 2) -> float:
    return round(value, digits)


def _slope(a: Point, b: Point, unit: float) -> float:
    """Change per 10 candles, in ATR."""
    return _r((b[1] - a[1]) / max(b[0] - a[0], 1) * 10 / unit)


def _head_and_shoulders(points: Sequence[Point], unit: float, top: bool) -> dict[str, Any]:
    (_, p1), (i2, p2), (_, p3), (i4, p4), (_, p5) = points
    nearer = max(p1, p5) if top else min(p1, p5)
    return {
        "shoulder_gap_atr": _r(abs(p1 - p5) / unit),
        "head_beyond_shoulders_atr": _r(abs(p3 - nearer) / unit),
        "neckline_slope_atr_per_10": _slope((i2, p2), (i4, p4), unit),
    }


def _double(points: Sequence[Point], unit: float) -> dict[str, Any]:
    (i1, p1), _, (i3, p3) = points
    return {"peak_gap_atr": _r(abs(p1 - p3) / unit), "peak_separation_candles": i3 - i1}


def _channel(
    evidence: dict[str, Any], series: CandleSeries, start: int, breakout: int, unit: float
) -> dict[str, Any] | None:
    upper, lower = _points(series, evidence["upper"]), _points(series, evidence["lower"])
    if upper is None or lower is None:
        return None
    up_slope = (upper[1][1] - upper[0][1]) / max(upper[1][0] - upper[0][0], 1)
    low_slope = (lower[1][1] - lower[0][1]) / max(lower[1][0] - lower[0][0], 1)

    def width(at: int) -> float:
        top = upper[1][1] + up_slope * (at - upper[1][0])
        bottom = lower[1][1] + low_slope * (at - lower[1][0])
        return top - bottom

    facts: dict[str, Any] = {
        "upper_slope_atr_per_10": _r(up_slope * 10 / unit),
        "lower_slope_atr_per_10": _r(low_slope * 10 / unit),
        "width_at_start_atr": _r(width(start) / unit),
        "width_at_breakout_atr": _r(width(breakout) / unit),
        "apex_progress": None,
    }
    if up_slope < low_slope:  # Converging, so the lines meet ahead.
        (ux, uy), (lx, ly) = upper[1], lower[1]
        apex = ux + (uy - ly - low_slope * (ux - lx)) / (low_slope - up_slope)
        if apex > start:
            facts["apex_progress"] = _r((breakout - start) / (apex - start))
    return facts


def _flag(points: Sequence[Point], evidence: dict[str, Any], height: float) -> dict[str, Any]:
    _, (_, top), (_, extreme) = points
    return {
        "pole_candles": evidence["pole_candles"],
        "flag_candles": evidence["flag_candles"],
        "retrace_share": _r(abs(top - extreme) / height) if height else None,
    }


def _labels(pattern_type: str, count: int, bullish: bool) -> list[str]:
    if pattern_type in ("head_and_shoulders", "inverse_head_and_shoulders"):
        return ["left_shoulder", "neckline_1", "head", "neckline_2", "right_shoulder"]
    if pattern_type in ("double_top", "double_bottom"):
        if bullish:
            return ["first_trough", "middle_peak", "second_trough"]
        return ["first_peak", "middle_trough", "second_peak"]
    if pattern_type in ("bull_flag", "bear_flag"):
        return ["pole_start", "pole_end", "flag_extreme"]
    return [f"pivot_{n}" for n in range(1, count + 1)]


def describe(
    pattern: DetectedPattern, series: CandleSeries, atr: FloatArray
) -> dict[str, Any] | None:
    """The shape of a chart pattern in numbers. None if its breakout candle is not in `series`."""
    breakout = _index(series, pattern.detected_at)
    if breakout is None:
        return None
    unit = float(atr[breakout])
    evidence = pattern.evidence
    points = _points(series, evidence.get("points", []))
    if unit != unit or unit <= 0 or not points:
        return None
    bullish = pattern.direction is Direction.BULLISH
    sign = 1 if bullish else -1
    close = float(series.close[breakout])
    span = float(series.high[breakout] - series.low[breakout])
    body = abs(close - float(series.open[breakout]))
    window = series.volume[max(breakout - VOLUME_LOOKBACK, 0) : breakout]
    average = float(window.mean()) if len(window) else 0.0
    height = float(evidence["height"])
    start = points[0][0]
    labels = _labels(pattern.pattern_type, len(points), bullish)
    facts: dict[str, Any] = {
        "type": pattern.pattern_type,
        "direction": pattern.direction.value,
        "timeframe": series.timeframe.value,
        "breakout_at": pattern.detected_at.isoformat(),
        "candles_in_pattern": breakout - start,
        "height_atr": _r(height / unit),
        "height_pct": _r(100 * height / close),
        "breakout_beyond_trigger_atr": _r(sign * (close - float(evidence["trigger"])) / unit),
        "breakout_body_share": _r(body / span) if span > 0 else None,
        "breakout_volume_ratio": _r(float(series.volume[breakout]) / average) if average else None,
        "back_to_invalidation_atr": _r(sign * (close - float(evidence["invalidation"])) / unit),
        "measured_moves_atr": [
            _r(sign * (float(m) - close) / unit) for m in evidence["measured_moves"]
        ],
        "points": [
            {"name": name, "price": price, "candles_before_breakout": breakout - index}
            for name, (index, price) in zip(labels, points, strict=True)
        ],
    }
    if "prior" in evidence:
        prior = _points(series, [evidence["prior"]])
        if prior:
            facts["move_into_pattern_atr"] = _r(abs(points[0][1] - prior[0][1]) / unit)
    kind = pattern.pattern_type
    if kind in ("head_and_shoulders", "inverse_head_and_shoulders"):
        facts |= _head_and_shoulders(points, unit, top=not bullish)
    elif kind in ("double_top", "double_bottom"):
        facts |= _double(points, unit)
    elif kind in CHANNELS:
        facts |= _channel(evidence, series, start, breakout, unit) or {}
    elif kind in ("bull_flag", "bear_flag"):
        facts |= _flag(points, evidence, height)
    return facts
