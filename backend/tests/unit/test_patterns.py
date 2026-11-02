import numpy as np

from tests.quant_data import candle, from_closes, random_walk
from trading_intel.domain.patterns import DetectedPattern, Direction
from trading_intel.market_structure.structure import analyse_structure
from trading_intel.market_structure.swings import Swing, find_swings
from trading_intel.pattern_detection.breakouts import breakouts
from trading_intel.pattern_detection.candles import engulfing, pin_bars_and_dojis
from trading_intel.pattern_detection.divergences import divergences
from trading_intel.pattern_detection.imbalance import fair_value_gaps, order_blocks
from trading_intel.pattern_detection.pipeline import detect_patterns
from trading_intel.technical_analysis.series import CandleSeries
from trading_intel.technical_analysis.volatility import atr
from trading_intel.technical_analysis.volume import relative_volume

FULL = random_walk(600, seed=9)


def series_of(*rows: tuple[float, float, float, float]) -> CandleSeries:
    return CandleSeries.of([candle(i, *row) for i, row in enumerate(rows)])


def test_bullish_engulfing() -> None:
    [found] = engulfing(series_of((105, 106, 99, 100), (99.5, 108, 99, 107)))
    assert found.pattern_type == "bullish_engulfing"
    assert found.direction is Direction.BULLISH


def test_bearish_engulfing() -> None:
    [found] = engulfing(series_of((100, 106, 99, 105), (105.5, 106, 98, 99)))
    assert found.pattern_type == "bearish_engulfing"


def test_a_smaller_body_is_not_engulfing() -> None:
    assert engulfing(series_of((105, 106, 99, 100), (101, 105, 100, 103))) == []


def test_bullish_pin_bar() -> None:
    [found] = [
        p
        for p in pin_bars_and_dojis(series_of((100, 101, 90, 100.5)))
        if p.pattern_type == "pin_bar"
    ]
    assert found.direction is Direction.BULLISH
    assert found.price_level == 90


def test_bearish_pin_bar() -> None:
    [found] = [
        p
        for p in pin_bars_and_dojis(series_of((100, 110, 99, 99.5)))
        if p.pattern_type == "pin_bar"
    ]
    assert found.direction is Direction.BEARISH


def test_doji() -> None:
    types = {p.pattern_type for p in pin_bars_and_dojis(series_of((100, 105, 95, 100.2)))}
    assert types == {"doji"}


def test_a_candle_with_no_range_is_ignored() -> None:
    assert pin_bars_and_dojis(series_of((100, 100, 100, 100))) == []


def test_bullish_fair_value_gap_and_its_filling() -> None:
    series = series_of(
        (100, 101, 99, 100), (100, 110, 100, 109), (109, 112, 105, 111), (111, 111, 104, 105)
    )
    [gap] = fair_value_gaps(series, atr(series))
    assert gap.direction is Direction.BULLISH
    assert (gap.zone_low, gap.zone_high) == (101, 105)
    assert gap.detected_at == series.close_time[2]
    assert gap.formed_at == series.close_time[1]
    assert gap.invalidated_at is None or gap.invalidated_at == series.close_time[3]


def test_bearish_fair_value_gap() -> None:
    series = series_of((110, 111, 109, 110), (110, 110, 100, 101), (101, 105, 99, 100))
    [gap] = fair_value_gaps(series, atr(series))
    assert gap.direction is Direction.BEARISH
    assert (gap.zone_low, gap.zone_high) == (105, 109)


def test_order_block_is_the_last_opposite_candle_before_a_bos() -> None:
    closes = [100, 101, 102, 103, 104, 105, 104, 103, 102, 101, 100, 101, 102, 103, 104, 106, 108.0]
    series = from_closes(closes, 0.1)
    swings = find_swings(series)
    state = analyse_structure(series, swings)
    [block] = order_blocks(series, state.events, atr(series))
    assert block.pattern_type == "order_block"
    assert block.direction is Direction.BULLISH
    assert block.formed_at == series.close_time[10]
    assert block.detected_at == state.events[0].time


def breakout_series(after: list[float]) -> CandleSeries:
    closes = [100, 101, 102, 103, 104, 105, 104, 103, 102, 101, 100, *([101.0] * 18), 103, 104]
    rows = []
    previous = 100.0
    for index, close in enumerate([*closes, *after]):
        volume = 40.0 if index == len(closes) else 10.0
        rows.append(
            candle(
                index,
                previous,
                max(previous, close) + 0.1,
                min(previous, close) - 0.1,
                close,
                volume,
            )
        )
        previous = close
    return CandleSeries.of(rows)


def relative(series: CandleSeries) -> np.ndarray:
    return relative_volume(series.volume)


def test_breakout_needs_volume() -> None:
    series = breakout_series([108, 109, 110, 111])
    events = analyse_structure(series, find_swings(series)).events
    found = breakouts(series, events, relative(series))
    assert [p.pattern_type for p in found] == ["breakout"]
    assert found[0].invalidated_at is None


def test_a_breakout_that_returns_inside_becomes_a_false_breakout() -> None:
    series = breakout_series([108, 104, 103, 102])
    events = analyse_structure(series, find_swings(series)).events
    found = breakouts(series, events, relative(series))
    assert {p.pattern_type for p in found} == {"breakout", "false_breakout"}
    failed = next(p for p in found if p.pattern_type == "breakout")
    assert failed.invalidated_at is not None
    assert (
        next(p for p in found if p.pattern_type == "false_breakout").direction is Direction.BEARISH
    )


def test_regular_bearish_divergence() -> None:
    at = FULL.close_time
    swings = [
        Swing("high", 10, 100, at[10], 13, at[13]),
        Swing("high", 20, 110, at[20], 23, at[23]),
    ]
    rsi = np.full(30, 50.0)
    rsi[10], rsi[20] = 70, 60
    [found] = divergences(swings, rsi)
    assert found.pattern_type == "regular_divergence"
    assert found.direction is Direction.BEARISH
    assert found.detected_at == at[23]


def test_hidden_bullish_divergence() -> None:
    at = FULL.close_time
    swings = [
        Swing("low", 10, 100, at[10], 13, at[13]),
        Swing("low", 20, 105, at[20], 23, at[23]),
    ]
    rsi = np.full(30, 50.0)
    rsi[10], rsi[20] = 40, 30
    [found] = divergences(swings, rsi)
    assert found.pattern_type == "hidden_divergence"
    assert found.direction is Direction.BULLISH


def test_divergence_needs_rsi_at_both_swings() -> None:
    at = FULL.close_time
    swings = [
        Swing("high", 1, 100, at[1], 4, at[4]),
        Swing("high", 20, 110, at[20], 23, at[23]),
    ]
    assert divergences(swings, np.full(30, np.nan)) == []


def test_every_pattern_is_rated_within_bounds_and_dated_sensibly() -> None:
    found = detect_patterns(FULL)
    assert len({p.pattern_type for p in found}) >= 10
    for pattern in found:
        assert 0 <= pattern.strength <= 100
        assert pattern.detected_at >= pattern.formed_at
        assert pattern.rule_version == "1"
        if pattern.invalidated_at:
            assert pattern.invalidated_at > pattern.detected_at


def test_detection_is_deterministic() -> None:
    assert detect_patterns(FULL) == detect_patterns(FULL)


def _known(patterns: list[DetectedPattern], moment: object) -> list[DetectedPattern]:
    visible = [p.as_known_at(moment) for p in patterns]  # type: ignore[arg-type]
    return sorted(
        (p for p in visible if p is not None),
        key=lambda p: (p.detected_at, p.pattern_type, p.formed_at, p.direction, str(p.price_level)),
    )


def test_no_pattern_depends_on_candles_after_it_was_detected() -> None:
    """The look-ahead test: a prefix must see exactly what the full run says it could see."""
    full = detect_patterns(FULL)
    for end in (120, 250, 433, 599):
        moment = FULL.close_time[end - 1]
        partial = _known(detect_patterns(FULL.upto(end)), moment)
        assert partial == _known(full, moment), f"look-ahead found at candle {end}"
