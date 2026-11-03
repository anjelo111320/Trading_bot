"""Chart patterns and the zigzag they are drawn on. Paths are synthetic test data."""

import json
from datetime import datetime
from itertools import pairwise

import numpy as np
import pytest

from tests.quant_data import from_closes, random_walk
from trading_intel.domain.patterns import DetectedPattern, Direction
from trading_intel.market_structure.zigzag import zigzag
from trading_intel.pattern_detection.chart_patterns import (
    channel_patterns,
    chart_patterns,
    double_tops_and_bottoms,
    flags,
    head_and_shoulders,
)
from trading_intel.technical_analysis.series import CandleSeries
from trading_intel.technical_analysis.volatility import atr

WICK = 0.2


def path(*waypoints: float, steps: int = 5) -> CandleSeries:
    """Closes moving in straight lines between waypoints, with a fixed wick."""
    closes = [waypoints[0]]
    for start, end in pairwise(waypoints):
        closes += [start + (end - start) * j / steps for j in range(1, steps + 1)]
    return from_closes(closes, WICK)


def unit(series: CandleSeries) -> np.ndarray:
    return np.full(len(series), 1.0)


def no_volume(series: CandleSeries) -> np.ndarray:
    return np.full(len(series), np.nan)


def first_close(
    series: CandleSeries, after: int, below: float | None = None, above: float | None = None
) -> int:
    for index in range(after, len(series)):
        close = float(series.close[index])
        if (below is not None and close < below) or (above is not None and close > above):
            return index
    raise AssertionError("no such close")


def test_zigzag_confirms_a_pivot_only_after_the_reversal() -> None:
    series = path(100, 110, 104, 112)
    pivots = zigzag(series, unit(series))
    assert [p.kind for p in pivots] == ["low", "high", "low"]
    peak = pivots[1]
    assert peak.price == pytest.approx(110 + WICK)
    # 110.2 minus 2.5 is 107.7. The first low at or below it confirms the peak.
    first = next(i for i in range(peak.index + 1, len(series)) if series.low[i] <= 107.7)
    assert peak.confirmed_index == first
    assert peak.confirmed_at == series.close_time[first]
    assert peak.label is None  # The first high has nothing to compare with.
    assert pivots[2].label == "HL"


def test_zigzag_is_prefix_stable() -> None:
    series = random_walk(500, seed=4)
    volatility = atr(series)
    full = zigzag(series, volatility)
    for end in (60, 200, 333, 499):
        partial = zigzag(series.upto(end), volatility[:end])
        assert partial == [p for p in full if p.confirmed_index < end], f"look-ahead at {end}"


def test_zigzag_waits_for_atr() -> None:
    series = path(100, 120, 90)
    assert zigzag(series, np.full(len(series), np.nan)) == []


def test_zigzag_pivots_alternate() -> None:
    series = random_walk(400, seed=11)
    pivots = zigzag(series, atr(series))
    assert len(pivots) > 10
    assert all(a.kind != b.kind for a, b in pairwise(pivots))
    assert all(p.confirmed_index > p.index for p in pivots)


HEAD_AND_SHOULDERS = (100, 120, 112, 126, 112, 120, 105)


def test_head_and_shoulders_top_breaks_its_neckline() -> None:
    series = path(*HEAD_AND_SHOULDERS)
    pivots = zigzag(series, unit(series))
    [found] = head_and_shoulders(series, pivots, unit(series), no_volume(series))
    neckline = 112 - WICK
    breakout = first_close(series, 20, below=neckline)
    assert found.pattern_type == "head_and_shoulders"
    assert found.direction is Direction.BEARISH
    assert found.detected_at == series.close_time[breakout]
    assert found.price_level == pytest.approx(neckline)
    assert found.evidence["invalidation"] == pytest.approx(120 + WICK)
    height = (126 + WICK) - neckline
    assert found.evidence["measured_moves"] == pytest.approx(
        [neckline - height, neckline - 2 * height]
    )
    json.dumps(found.evidence)


def test_inverse_head_and_shoulders_is_the_mirror() -> None:
    series = path(*(200 - x for x in HEAD_AND_SHOULDERS))
    pivots = zigzag(series, unit(series))
    [found] = head_and_shoulders(series, pivots, unit(series), no_volume(series))
    assert found.pattern_type == "inverse_head_and_shoulders"
    assert found.direction is Direction.BULLISH
    assert found.evidence["invalidation"] == pytest.approx(80 - WICK)


def test_no_head_and_shoulders_without_a_neckline_close() -> None:
    series = path(100, 120, 112, 126, 112, 120, 113.5)
    pivots = zigzag(series, unit(series))
    assert head_and_shoulders(series, pivots, unit(series), no_volume(series)) == []


def test_lopsided_shoulders_are_not_head_and_shoulders() -> None:
    series = path(100, 120, 112, 126, 112, 116, 105)
    pivots = zigzag(series, unit(series))
    assert head_and_shoulders(series, pivots, unit(series), no_volume(series)) == []


def test_head_and_shoulders_needs_a_rise_before_it() -> None:
    # The low before the left shoulder sits above the neckline, so price did not rise into it.
    series = path(115, 120, 112, 126, 112, 120, 105)
    pivots = zigzag(series, unit(series))
    assert head_and_shoulders(series, pivots, unit(series), no_volume(series)) == []


def test_double_bottom_confirms_above_the_middle_peak() -> None:
    series = path(120, 100, 108, 100.3, 112, steps=6)
    pivots = zigzag(series, unit(series))
    [found] = double_tops_and_bottoms(series, pivots, unit(series), no_volume(series))
    assert found.pattern_type == "double_bottom"
    assert found.direction is Direction.BULLISH
    assert found.price_level == pytest.approx(108 + WICK)
    assert found.evidence["invalidation"] == pytest.approx(100.3 - WICK)
    assert found.evidence["height"] == pytest.approx((108 + WICK) - (100 - WICK))


def test_peaks_too_close_together_are_not_a_double_top() -> None:
    series = path(100, 120, 112, 120.3, 108, steps=3)
    pivots = zigzag(series, unit(series))
    assert double_tops_and_bottoms(series, pivots, unit(series), no_volume(series)) == []


def test_a_clearly_higher_second_peak_is_not_a_double_top() -> None:
    series = path(100, 120, 112, 124, 108, steps=6)
    pivots = zigzag(series, unit(series))
    assert double_tops_and_bottoms(series, pivots, unit(series), no_volume(series)) == []


def channels(series: CandleSeries) -> list[tuple[str, Direction]]:
    pivots = zigzag(series, unit(series))
    found = channel_patterns(series, pivots, unit(series), no_volume(series))
    return [(p.pattern_type, p.direction) for p in found]


def test_symmetrical_triangle_breaks_down() -> None:
    assert channels(path(100, 120, 100, 116, 104, 112, 96)) == [
        ("symmetrical_triangle", Direction.BEARISH)
    ]


def test_ascending_triangle_breaks_up() -> None:
    assert channels(path(100, 120, 104, 120.1, 108, 120, 113, 126)) == [
        ("ascending_triangle", Direction.BULLISH)
    ]


def test_rectangle_breaks_down() -> None:
    assert channels(path(100, 120, 100.2, 120.1, 100.1, 120, 95)) == [
        ("rectangle", Direction.BEARISH)
    ]


def test_rising_wedge_breaks_down() -> None:
    assert channels(path(96, 110, 100, 116, 108, 120, 98)) == [("rising_wedge", Direction.BEARISH)]


def test_broadening_formation() -> None:
    found = channels(path(110, 114, 106, 118, 102, 122, 90))
    assert found == [("broadening", Direction.BEARISH)]


def test_bull_flag_breaks_above_the_pole() -> None:
    closes = [100.0] * 6 + [102, 104, 106, 108, 110, 109.4, 108.6, 107.8, 107.2, 109.5, 112]
    series = from_closes(closes, WICK)
    [found] = flags(series, unit(series), no_volume(series))
    assert found.pattern_type == "bull_flag"
    assert found.direction is Direction.BULLISH
    assert found.detected_at == series.close_time[len(closes) - 1]
    assert found.price_level == pytest.approx(110 + WICK)
    assert found.evidence["invalidation"] == pytest.approx(107.2 - WICK)


def test_a_deep_pullback_is_not_a_flag() -> None:
    closes = [100.0] * 6 + [102, 104, 106, 108, 110, 107, 104, 103, 104.5, 109.5, 112]
    series = from_closes(closes, WICK)
    assert flags(series, unit(series), no_volume(series)) == []


def test_bear_flag_is_the_mirror() -> None:
    closes = [
        200 - c
        for c in [100.0] * 6 + [102, 104, 106, 108, 110, 109.4, 108.6, 107.8, 107.2, 109.5, 112]
    ]
    series = from_closes(closes, WICK)
    [found] = flags(series, unit(series), no_volume(series))
    assert found.pattern_type == "bear_flag"
    assert found.direction is Direction.BEARISH


def test_a_close_back_through_the_invalidation_level_invalidates_the_pattern() -> None:
    series = path(*HEAD_AND_SHOULDERS, 122)
    pivots = zigzag(series, unit(series))
    [found] = head_and_shoulders(series, pivots, unit(series), no_volume(series))
    assert found.invalidated_at is not None
    assert found.invalidated_at > found.detected_at


def test_chart_patterns_on_a_random_walk_are_prefix_stable() -> None:
    series = random_walk(1500, seed=21)
    volatility = atr(series)
    ratio = np.full(len(series), np.nan)
    full = chart_patterns(series, volatility, ratio)
    assert len(full) >= 5, "the walk should contain some chart patterns"

    def known(patterns: list[DetectedPattern], moment: datetime) -> list[DetectedPattern]:
        visible = [p.as_known_at(moment) for p in patterns]
        return sorted(
            (p for p in visible if p is not None),
            key=lambda p: (
                p.detected_at,
                p.pattern_type,
                p.formed_at,
                p.direction,
                str(p.price_level),
            ),
        )

    for end in (400, 800, 1200, 1499):
        moment = series.close_time[end - 1]
        partial = chart_patterns(series.upto(end), volatility[:end], ratio[:end])
        assert known(partial, moment) == known(full, moment), f"look-ahead at candle {end}"
