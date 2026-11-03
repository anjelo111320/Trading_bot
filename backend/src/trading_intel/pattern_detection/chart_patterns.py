"""Chart patterns on ATR zigzag pivots, dated by their breakout close.

Geometry follows Lo, Mamaysky and Wang (2000), with tolerances in ATR instead of percent.
A pattern exists only once a candle closes beyond its trigger line, because unconfirmed
tops and bottoms mostly fail (docs/26-PATTERN-RESEARCH.md). Rules are in
docs/25-PATTERN-RULES.md.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Final, Literal

from trading_intel.domain.patterns import DetectedPattern, Direction, clamp_score
from trading_intel.market_structure.swings import Swing
from trading_intel.market_structure.zigzag import zigzag
from trading_intel.technical_analysis.series import CandleSeries, FloatArray

SIMILAR_ATR: Final = 1.0  # Shoulders, double-top peaks and neckline troughs.
FLAT_ATR: Final = 0.5  # Rectangle sides and the flat side of a triangle.
MIN_PEAK_GAP: Final = 10  # Candles between the two peaks of a double top.
FLAG_POLE_ATR: Final = 5.0
FLAG_POLE_MAX: Final = 12
FLAG_MIN: Final = 3
FLAG_MAX: Final = 24
FLAG_RETRACE: Final = 0.5
MEASURED_MULTIPLES: Final = (1.0, 2.0)

ChannelKind = Literal[
    "rectangle",
    "ascending_triangle",
    "descending_triangle",
    "symmetrical_triangle",
    "rising_wedge",
    "falling_wedge",
    "broadening",
]


@dataclass(frozen=True)
class _Point:
    index: int
    price: float


def _line(a: _Point, b: _Point, index: int) -> float:
    if b.index == a.index:
        return b.price
    return a.price + (b.price - a.price) * (index - a.index) / (b.index - a.index)


def _iso(series: CandleSeries, index: int) -> str:
    return series.close_time[index].isoformat()


def _first_close_beyond(
    series: CandleSeries, start: int, level: float, bullish: bool
) -> int | None:
    """First candle from `start` whose close passes `level` against the trade."""
    for index in range(start, len(series)):
        close = float(series.close[index])
        if (bullish and close < level) or (not bullish and close > level):
            return index
    return None


def _strength(relative_volume: FloatArray, index: int) -> float:
    """Ranks breakouts by volume against the 20 before, as Bulkowski found that helps."""
    ratio = float(relative_volume[index])
    return 50.0 if ratio != ratio else clamp_score(50 * ratio)


def _finish(
    series: CandleSeries,
    relative_volume: FloatArray,
    *,
    pattern_type: str,
    bullish: bool,
    points: Sequence[_Point],
    breakout: int,
    trigger: float,
    height: float,
    invalidation: float,
    measure_from: float,
    extra: dict[str, object] | None = None,
) -> DetectedPattern:
    sign = 1 if bullish else -1
    prices = [p.price for p in points]
    later = _first_close_beyond(series, breakout + 1, invalidation, bullish)
    pattern = DetectedPattern(
        pattern_type=pattern_type,
        direction=Direction.BULLISH if bullish else Direction.BEARISH,
        formed_at=series.close_time[points[0].index],
        detected_at=series.close_time[breakout],
        price_level=round(trigger, 8),
        zone_low=min(prices),
        zone_high=max(prices),
        strength=_strength(relative_volume, breakout),
        evidence={
            "points": [[_iso(series, p.index), p.price] for p in points],
            "trigger": round(trigger, 8),
            "breakout_close": float(series.close[breakout]),
            "height": round(height, 8),
            "invalidation": invalidation,
            "measured_moves": [
                round(measure_from + sign * m * height, 8) for m in MEASURED_MULTIPLES
            ],
            **(extra or {}),
        },
    )
    return pattern if later is None else pattern.invalidated(series.close_time[later])


def _next_confirmation(pivots: Sequence[Swing], position: int, length: int) -> int:
    return pivots[position].confirmed_index if position < len(pivots) else length - 1


def head_and_shoulders(
    series: CandleSeries, pivots: Sequence[Swing], atr: FloatArray, relative_volume: FloatArray
) -> list[DetectedPattern]:
    """Three peaks with the middle highest, confirmed by a close through the neckline.

    E5, the right shoulder, is the extreme since E4 and need not be a confirmed pivot yet.
    The first close through the neckline decides: the shape passes then, or never.
    """
    found: list[DetectedPattern] = []
    close = series.close
    for k in range(4, len(pivots)):
        e0, e1, e2, e3, e4 = pivots[k - 4 : k + 1]
        top = e4.kind == "low"
        sign = 1 if top else -1  # Prices are flipped for bottoms, so one rule serves both.
        extreme = series.high if top else series.low
        deadline = _next_confirmation(pivots, k + 2, len(series))
        start = e4.confirmed_index + 1
        if start > deadline or start >= len(series):
            continue
        shoulder = max(range(e4.index + 1, start), key=lambda i: (sign * float(extreme[i]), -i))
        for t in range(start, deadline + 1):
            if sign * float(extreme[t - 1]) > sign * float(extreme[shoulder]):
                shoulder = t - 1
            right = float(extreme[shoulder])
            if sign * right > sign * e3.price:
                break  # The right shoulder rose above the head.
            neckline = _line(_Point(e2.index, e2.price), _Point(e4.index, e4.price), t)
            if sign * (float(close[t]) - neckline) >= 0:
                continue
            tolerance = SIMILAR_ATR * float(atr[t])
            valid = (
                sign * (e3.price - e1.price) > 0
                and sign * (e3.price - right) > 0
                and abs(e1.price - right) <= tolerance
                and abs(e2.price - e4.price) <= tolerance
                and sign * (min(e2.price, e4.price, key=lambda p: sign * p) - e0.price) > 0
            )
            if valid:
                head_neck = _line(_Point(e2.index, e2.price), _Point(e4.index, e4.price), e3.index)
                found.append(
                    _finish(
                        series,
                        relative_volume,
                        pattern_type="head_and_shoulders" if top else "inverse_head_and_shoulders",
                        bullish=not top,
                        points=[
                            _Point(e1.index, e1.price),
                            _Point(e2.index, e2.price),
                            _Point(e3.index, e3.price),
                            _Point(e4.index, e4.price),
                            _Point(shoulder, right),
                        ],
                        breakout=t,
                        trigger=neckline,
                        height=abs(e3.price - head_neck),
                        invalidation=right,
                        measure_from=neckline,
                        extra={"prior": [_iso(series, e0.index), e0.price]},
                    )
                )
            break
    return found


def double_tops_and_bottoms(
    series: CandleSeries, pivots: Sequence[Swing], atr: FloatArray, relative_volume: FloatArray
) -> list[DetectedPattern]:
    """Two similar peaks, confirmed by a close through the trough between them."""
    found: list[DetectedPattern] = []
    close = series.close
    for k in range(2, len(pivots)):
        e0, e1, e2 = pivots[k - 2 : k + 1]
        top = e2.kind == "low"
        sign = 1 if top else -1
        extreme = series.high if top else series.low
        deadline = _next_confirmation(pivots, k + 2, len(series))
        start = e2.confirmed_index + 1
        if start > deadline or start >= len(series):
            continue
        second = max(range(e2.index + 1, start), key=lambda i: (sign * float(extreme[i]), -i))
        for t in range(start, deadline + 1):
            if sign * float(extreme[t - 1]) > sign * float(extreme[second]):
                second = t - 1
            peak = float(extreme[second])
            tolerance = SIMILAR_ATR * float(atr[t])
            if sign * (peak - e1.price) > tolerance:
                break  # A clearly higher second peak is a new high, not a double top.
            if sign * (float(close[t]) - e2.price) >= 0:
                continue
            valid = (
                abs(e1.price - peak) <= tolerance
                and second - e1.index >= MIN_PEAK_GAP
                and sign * (e2.price - e0.price) > 0
            )
            if valid:
                found.append(
                    _finish(
                        series,
                        relative_volume,
                        pattern_type="double_top" if top else "double_bottom",
                        bullish=not top,
                        points=[
                            _Point(e1.index, e1.price),
                            _Point(e2.index, e2.price),
                            _Point(second, peak),
                        ],
                        breakout=t,
                        trigger=e2.price,
                        height=abs(max(e1.price, peak, key=lambda p: sign * p) - e2.price),
                        invalidation=peak,
                        measure_from=e2.price,
                        extra={"prior": [_iso(series, e0.index), e0.price]},
                    )
                )
            break
    return found


def _classify(tops: Sequence[_Point], bottoms: Sequence[_Point], unit: float) -> ChannelKind | None:
    top_prices = [p.price for p in tops]
    bottom_prices = [p.price for p in bottoms]
    flat_top = max(top_prices) - min(top_prices) <= FLAT_ATR * unit
    flat_bottom = max(bottom_prices) - min(bottom_prices) <= FLAT_ATR * unit
    rising_tops = all(a < b for a, b in pairwise(top_prices))
    falling_tops = all(a > b for a, b in pairwise(top_prices))
    rising_bottoms = all(a < b for a, b in pairwise(bottom_prices))
    falling_bottoms = all(a > b for a, b in pairwise(bottom_prices))

    def slope(points: Sequence[_Point]) -> float:
        a, b = points[-2], points[-1]
        return (b.price - a.price) / (b.index - a.index)

    converging = slope(tops) < slope(bottoms)
    if flat_top and flat_bottom and min(top_prices) > max(bottom_prices):
        return "rectangle"
    if flat_top and rising_bottoms:
        return "ascending_triangle"
    if flat_bottom and falling_tops:
        return "descending_triangle"
    if falling_tops and rising_bottoms:
        return "symmetrical_triangle"
    if rising_tops and rising_bottoms and converging:
        return "rising_wedge"
    if falling_tops and falling_bottoms and converging:
        return "falling_wedge"
    if rising_tops and falling_bottoms:
        return "broadening"
    return None


def channel_patterns(
    series: CandleSeries, pivots: Sequence[Swing], atr: FloatArray, relative_volume: FloatArray
) -> list[DetectedPattern]:
    """Rectangles, triangles, wedges and broadening formations on five confirmed pivots.

    The pattern lives from the fifth pivot's confirmation until the next pivot confirms.
    The first close outside either boundary is the breakout, in that direction.
    """
    found: list[DetectedPattern] = []
    close = series.close
    for k in range(4, len(pivots)):
        window = pivots[k - 4 : k + 1]
        points = [_Point(p.index, p.price) for p in window]
        tops = [_Point(p.index, p.price) for p in window if p.kind == "high"]
        bottoms = [_Point(p.index, p.price) for p in window if p.kind == "low"]
        formed = window[-1].confirmed_index
        unit = float(atr[formed])
        if unit != unit:
            continue
        kind = _classify(tops, bottoms, unit)
        if kind is None:
            continue
        deadline = _next_confirmation(pivots, k + 1, len(series))
        highest, lowest = max(p.price for p in tops), min(p.price for p in bottoms)
        for t in range(formed, deadline + 1):
            if kind == "rectangle":
                upper, lower = highest, lowest
            else:
                upper, lower = _line(tops[-2], tops[-1], t), _line(bottoms[-2], bottoms[-1], t)
            if upper <= lower:
                break  # Past the apex, the pattern has run out.
            price = float(close[t])
            if lower <= price <= upper:
                continue
            bullish = price > upper
            found.append(
                _finish(
                    series,
                    relative_volume,
                    pattern_type=kind,
                    bullish=bullish,
                    points=points,
                    breakout=t,
                    trigger=upper if bullish else lower,
                    height=highest - lowest,
                    invalidation=bottoms[-1].price if bullish else tops[-1].price,
                    measure_from=upper if bullish else lower,
                    extra={
                        "upper": [[_iso(series, p.index), p.price] for p in tops[-2:]],
                        "lower": [[_iso(series, p.index), p.price] for p in bottoms[-2:]],
                    },
                )
            )
            break
    return found


def flags(
    series: CandleSeries, atr: FloatArray, relative_volume: FloatArray
) -> list[DetectedPattern]:
    """A steep pole, a short pullback of at most half of it, then a close beyond the pole.

    Covers flags and pennants: the pullback's shape is not tested, only its depth and length.
    """
    found: list[DetectedPattern] = []
    high, low, close = series.high, series.low, series.close
    seen: set[tuple[int, bool]] = set()
    for t in range(FLAG_MIN + 1, len(series)):
        window = range(max(t - FLAG_MAX, 1), t - FLAG_MIN + 1)
        for bullish in (True, False):
            sign = 1 if bullish else -1
            extreme = high if bullish else low
            opposite = low if bullish else high
            top = max(window, key=lambda i: (sign * float(extreme[i]), -i))
            if (top, bullish) in seen:
                continue
            pole_top = float(extreme[top])
            inside = range(top + 1, t)
            if any(sign * float(extreme[i]) > sign * pole_top for i in inside):
                continue
            if sign * (float(close[t]) - pole_top) <= 0:
                continue
            seen.add((top, bullish))
            unit = float(atr[top])
            starts = range(max(top - FLAG_POLE_MAX, 0), top)
            if unit != unit or not starts:
                continue
            base = min(starts, key=lambda i: (sign * float(opposite[i]), -i))
            pole = sign * (pole_top - float(opposite[base]))
            flag_end = min(inside, key=lambda i: sign * float(opposite[i]))
            flag_extreme = float(opposite[flag_end])
            if (
                pole < FLAG_POLE_ATR * unit
                or sign * (pole_top - flag_extreme) > FLAG_RETRACE * pole
            ):
                continue
            found.append(
                _finish(
                    series,
                    relative_volume,
                    pattern_type="bull_flag" if bullish else "bear_flag",
                    bullish=bullish,
                    points=[
                        _Point(base, float(opposite[base])),
                        _Point(top, pole_top),
                        _Point(flag_end, flag_extreme),
                    ],
                    breakout=t,
                    trigger=pole_top,
                    height=pole,
                    invalidation=flag_extreme,
                    measure_from=flag_extreme,
                    extra={"pole_candles": top - base, "flag_candles": t - top - 1},
                )
            )
    return found


def chart_patterns(
    series: CandleSeries, atr: FloatArray, relative_volume: FloatArray
) -> list[DetectedPattern]:
    pivots = zigzag(series, atr)
    return [
        *head_and_shoulders(series, pivots, atr, relative_volume),
        *double_tops_and_bottoms(series, pivots, atr, relative_volume),
        *channel_patterns(series, pivots, atr, relative_volume),
        *flags(series, atr, relative_volume),
    ]
