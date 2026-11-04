"""Pattern shapes as numbers. Paths are synthetic test data; ATR is fixed at 1."""

import json

import numpy as np
import pytest

from tests.quant_data import from_closes
from tests.unit.test_chart_patterns import HEAD_AND_SHOULDERS, WICK, no_volume, path, unit
from trading_intel.market_structure.zigzag import zigzag
from trading_intel.pattern_detection.chart_patterns import (
    channel_patterns,
    flags,
    head_and_shoulders,
)
from trading_intel.pattern_detection.describe import describe

HS = path(*HEAD_AND_SHOULDERS)
[HS_PATTERN] = head_and_shoulders(HS, zigzag(HS, unit(HS)), unit(HS), no_volume(HS))


def test_head_and_shoulders_in_numbers() -> None:
    facts = describe(HS_PATTERN, HS, unit(HS))
    assert facts is not None
    assert facts["type"] == "head_and_shoulders"
    assert facts["direction"] == "bearish"
    assert facts["candles_in_pattern"] == 23
    assert facts["height_atr"] == pytest.approx(14.4)
    assert facts["breakout_beyond_trigger_atr"] == pytest.approx(0.8)
    assert facts["breakout_body_share"] == pytest.approx(0.88)
    assert facts["breakout_volume_ratio"] == pytest.approx(1.0)
    assert facts["back_to_invalidation_atr"] == pytest.approx(9.2)
    assert facts["measured_moves_atr"] == pytest.approx([13.6, 28.0])
    assert facts["move_into_pattern_atr"] == pytest.approx(20.4)
    assert facts["shoulder_gap_atr"] == 0.0
    assert facts["head_beyond_shoulders_atr"] == pytest.approx(6.0)
    assert facts["neckline_slope_atr_per_10"] == 0.0
    assert [p["name"] for p in facts["points"]] == [
        "left_shoulder",
        "neckline_1",
        "head",
        "neckline_2",
        "right_shoulder",
    ]
    assert facts["points"][2] == {
        "name": "head",
        "price": 126 + WICK,
        "candles_before_breakout": 13,
    }
    json.dumps(facts)  # Sent to Claude as text, so it must serialise.


def test_a_symmetrical_triangle_reports_slopes_and_apex_progress() -> None:
    series = path(100, 120, 100, 116, 104, 112, 96)
    [pattern] = channel_patterns(
        series, zigzag(series, unit(series)), unit(series), no_volume(series)
    )
    facts = describe(pattern, series, unit(series))
    assert facts is not None
    assert facts["upper_slope_atr_per_10"] == pytest.approx(-4.0)
    assert facts["lower_slope_atr_per_10"] == pytest.approx(4.0)
    assert facts["width_at_start_atr"] == pytest.approx(22.4)
    assert facts["width_at_breakout_atr"] == pytest.approx(4.8)
    assert facts["apex_progress"] == pytest.approx(0.79)  # Lines meet at candle 33.


def test_a_flag_reports_its_pole_and_pullback() -> None:
    closes = [100.0] * 6 + [102, 104, 106, 108, 110, 109.4, 108.6, 107.8, 107.2, 109.5, 112]
    series = from_closes(closes, WICK)
    [pattern] = flags(series, unit(series), no_volume(series))
    facts = describe(pattern, series, unit(series))
    assert facts is not None
    assert facts["height_atr"] == pytest.approx(10.4)
    assert facts["pole_candles"] == 4
    assert facts["flag_candles"] == 5
    assert facts["retrace_share"] == pytest.approx(0.31)
    assert [p["name"] for p in facts["points"]] == ["pole_start", "pole_end", "flag_extreme"]


def test_only_candles_up_to_the_breakout_are_read() -> None:
    breakout = HS.close_time.index(HS_PATTERN.detected_at)
    later = path(*HEAD_AND_SHOULDERS, 140)
    assert describe(HS_PATTERN, HS.upto(breakout + 1), unit(HS)[: breakout + 1]) == describe(
        HS_PATTERN, later, unit(later)
    )


def test_nothing_is_described_without_the_breakout_candle_or_atr() -> None:
    breakout = HS.close_time.index(HS_PATTERN.detected_at)
    assert describe(HS_PATTERN, HS.upto(breakout), unit(HS)[:breakout]) is None
    assert describe(HS_PATTERN, HS, np.full(len(HS), np.nan)) is None
