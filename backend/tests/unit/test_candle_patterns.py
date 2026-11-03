"""Trend-aware candle patterns. Rows are synthetic test data."""

import pytest

from tests.quant_data import candle
from trading_intel.domain.patterns import Direction
from trading_intel.pattern_detection.candles import prior_trend, trend_candle_patterns
from trading_intel.technical_analysis.series import CandleSeries
from trading_intel.technical_analysis.volatility import atr

Row = tuple[float, float, float, float]


def lead_in(trend: str) -> list[Row]:
    """Twenty steady candles ending at 100: falling, rising or flat."""
    step = {"down": -1.0, "up": 1.0, "flat": 0.0}[trend]
    rows: list[Row] = []
    previous = 100 - 20 * step
    for _ in range(20):
        close = previous + step
        rows.append((previous, max(previous, close) + 0.5, min(previous, close) - 0.5, close))
        previous = close
    return rows


def found_on_last(trend: str, *rows: Row) -> dict[str, Direction]:
    """Pattern types detected on the final candle, with their direction."""
    all_rows = [*lead_in(trend), *rows]
    series = CandleSeries.of([candle(i, *row) for i, row in enumerate(all_rows)])
    last = series.close_time[-1]
    return {
        p.pattern_type: p.direction
        for p in trend_candle_patterns(series, atr(series))
        if p.detected_at == last
    }


HAMMER: Row = (99, 100.2, 95, 100)
STAR: Row = (100, 105, 99.8, 101)


def test_prior_trend_reads_the_ten_closes_before_a_pattern() -> None:
    for trend in ("down", "up", "flat"):
        rows = lead_in(trend)
        series = CandleSeries.of([candle(i, *row) for i, row in enumerate([*rows, HAMMER])])
        expected = "none" if trend == "flat" else trend
        assert prior_trend(series, atr(series), len(rows)) == expected


def test_hammer_after_a_fall() -> None:
    assert found_on_last("down", HAMMER) == {"hammer": Direction.BULLISH}


def test_the_same_shape_after_a_rise_is_a_hanging_man() -> None:
    assert found_on_last("up", HAMMER) == {"hanging_man": Direction.BEARISH}


def test_the_shape_without_a_trend_is_nothing() -> None:
    assert found_on_last("flat", HAMMER) == {}


def test_shooting_star_and_inverted_hammer() -> None:
    assert found_on_last("up", STAR) == {"shooting_star": Direction.BEARISH}
    assert found_on_last("down", STAR) == {"inverted_hammer": Direction.BULLISH}


def test_dragonfly_doji_after_a_fall() -> None:
    found = found_on_last("down", (100, 100.05, 96, 100))
    assert found["dragonfly_doji"] is Direction.BULLISH


def test_gravestone_doji_after_a_rise() -> None:
    found = found_on_last("up", (100, 104, 99.95, 100))
    assert found["gravestone_doji"] is Direction.BEARISH


def test_marubozu_needs_a_large_full_body() -> None:
    assert found_on_last("flat", (100, 103.05, 99.95, 103)) == {
        "bullish_marubozu": Direction.BULLISH
    }
    assert found_on_last("flat", (100, 101, 98, 100.5)) == {}


def test_bullish_harami() -> None:
    found = found_on_last("down", (102, 102.2, 96.8, 97), (98, 99.2, 97.8, 99))
    assert found["bullish_harami"] is Direction.BULLISH


def test_bearish_harami() -> None:
    found = found_on_last("up", (98, 103.2, 97.8, 103), (102, 102.2, 100.8, 101))
    assert found["bearish_harami"] is Direction.BEARISH


def test_piercing_line_closes_above_the_middle_of_the_first_body() -> None:
    found = found_on_last("down", (101, 101.2, 95.8, 96), (96, 99.7, 95.9, 99.5))
    assert found["piercing_line"] is Direction.BULLISH
    shallow = found_on_last("down", (101, 101.2, 95.8, 96), (96, 98.2, 95.9, 98))
    assert "piercing_line" not in shallow


def test_dark_cloud_cover() -> None:
    found = found_on_last("up", (99, 104.2, 98.8, 104), (104, 104.1, 100.3, 100.5))
    assert found["dark_cloud_cover"] is Direction.BEARISH


def test_tweezer_bottom() -> None:
    found = found_on_last("down", (101, 101.2, 97, 97.5), (97.5, 99.5, 97.05, 99))
    assert found["tweezer_bottom"] is Direction.BULLISH


def test_inside_bar_needs_no_trend() -> None:
    found = found_on_last("flat", (100, 104, 96, 101), (101, 103, 98, 102))
    assert found["inside_bar"] is Direction.NEUTRAL


def test_morning_star() -> None:
    found = found_on_last(
        "down", (101, 101.2, 95.8, 96), (96, 96.5, 95, 95.8), (95.8, 100.2, 95.7, 100)
    )
    assert found["morning_star"] is Direction.BULLISH


def test_evening_star() -> None:
    found = found_on_last(
        "up", (99, 104.2, 98.8, 104), (104, 105, 103.5, 104.2), (104.2, 104.3, 99.8, 100)
    )
    assert found["evening_star"] is Direction.BEARISH


def test_three_white_soldiers() -> None:
    found = found_on_last(
        "down", (100, 102.1, 99.9, 102), (102, 104.1, 101.9, 104), (104, 106.1, 103.9, 106)
    )
    assert found["three_white_soldiers"] is Direction.BULLISH


def test_three_black_crows() -> None:
    found = found_on_last("up", (100, 100.1, 97.9, 98), (98, 98.1, 95.9, 96), (96, 96.1, 93.9, 94))
    assert found["three_black_crows"] is Direction.BEARISH


def test_three_inside_up() -> None:
    found = found_on_last(
        "down", (102, 102.2, 96.8, 97), (98, 99.2, 97.8, 99), (99, 103.2, 98.8, 103)
    )
    assert found["three_inside_up"] is Direction.BULLISH


def test_three_outside_up() -> None:
    found = found_on_last(
        "down", (100.5, 100.7, 98.8, 99), (99, 101.6, 98.9, 101.5), (101.5, 102.7, 101.3, 102.5)
    )
    assert found["three_outside_up"] is Direction.BULLISH


@pytest.mark.parametrize("trend", ["down", "up", "flat"])
def test_every_candle_pattern_is_bounded_and_dated(trend: str) -> None:
    rows = [*lead_in(trend), HAMMER, STAR, (100, 103.05, 99.95, 103)]
    series = CandleSeries.of([candle(i, *row) for i, row in enumerate(rows)])
    for pattern in trend_candle_patterns(series, atr(series)):
        assert 0 <= pattern.strength <= 100
        assert pattern.formed_at <= pattern.detected_at
        assert pattern.evidence["prior_trend"] in ("up", "down", "none")
