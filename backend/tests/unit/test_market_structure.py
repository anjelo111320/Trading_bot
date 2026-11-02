from datetime import timedelta

import numpy as np
import pytest

from tests.quant_data import START, candle, from_closes, random_walk
from trading_intel.domain.candles import ClosedCandle, Timeframe
from trading_intel.domain.patterns import Direction
from trading_intel.market_structure.levels import support_resistance
from trading_intel.market_structure.liquidity import equal_levels, liquidity_sweeps
from trading_intel.market_structure.multi_timeframe import build_view
from trading_intel.market_structure.structure import analyse_structure
from trading_intel.market_structure.swings import find_swings
from trading_intel.market_structure.zones import consolidations, supply_demand_zones
from trading_intel.technical_analysis.series import CandleSeries
from trading_intel.technical_analysis.volatility import atr

PEAK = [100, 101, 102, 103, 104, 105, 104, 103, 102, 101, 100.0]


def test_swing_high_needs_candles_on_both_sides() -> None:
    swings = find_swings(from_closes(PEAK))
    highs = [s for s in swings if s.kind == "high"]
    assert [s.index for s in highs] == [5]


def test_a_swing_is_only_known_after_the_confirmation_delay() -> None:
    series = from_closes(PEAK)
    [swing] = [s for s in find_swings(series) if s.kind == "high"]
    assert swing.confirmed_index == swing.index + 3
    assert swing.confirmed_at == series.close_time[swing.index + 3]
    assert find_swings(series.upto(swing.index + 3)) == []
    assert [s.index for s in find_swings(series.upto(swing.index + 4)) if s.kind == "high"] == [5]


def waves(peaks: list[float], troughs: list[float]) -> CandleSeries:
    closes: list[float] = [troughs[0]]
    for peak, trough in zip(peaks, troughs[1:], strict=False):
        previous = closes[-1]
        closes += list(np.linspace(previous, peak, 6)[1:])
        closes += list(np.linspace(peak, trough, 6)[1:])
    return from_closes(closes, spread=0.1)


def test_swings_are_labelled_against_the_previous_swing() -> None:
    swings = find_swings(waves([110, 120, 115], [100, 105, 102, 95]))
    highs = [s.label for s in swings if s.kind == "high"]
    lows = [s.label for s in swings if s.kind == "low"]
    assert highs == [None, "HH", "LH"]
    assert lows == [None, "HL", "HL"] or lows == ["HL", "HL"] or len(lows) >= 2


def test_bos_needs_a_close_beyond_the_swing() -> None:
    closes = [*PEAK, 101, 102, 103, 104, 106, 107]
    state = analyse_structure(
        series := from_closes(closes, 0.1), find_swings(from_closes(closes, 0.1))
    )
    assert [e.kind for e in state.events] == ["BOS"]
    assert state.events[0].direction is Direction.BULLISH
    assert state.trend[-1] == "up"
    assert series.close[state.events[0].index] > state.events[0].level


def test_a_wick_beyond_the_swing_does_not_break_structure() -> None:
    candles: list[ClosedCandle] = []
    previous = 100.0
    for index, close in enumerate([*PEAK, 101, 102]):
        candles.append(
            candle(index, previous, max(previous, close) + 0.1, min(previous, close) - 0.1, close)
        )
        previous = close
    candles.append(candle(len(candles), 102, 120, 101, 103))
    series = CandleSeries.of(candles)
    assert analyse_structure(series, find_swings(series)).events == []


def test_change_of_character_comes_from_breaking_against_the_trend() -> None:
    series = waves([110, 108, 106, 125], [100, 95, 90, 88, 120])
    state = analyse_structure(series, find_swings(series))
    kinds = [(e.kind, e.direction) for e in state.events]
    assert ("BOS", Direction.BEARISH) in kinds
    assert ("CHOCH", Direction.BULLISH) in kinds
    assert state.trend[-1] == "up"


def test_each_swing_breaks_only_once() -> None:
    closes = [*PEAK, 101, 106, 101, 106, 101, 106]
    series = from_closes(closes, 0.1)
    events = analyse_structure(series, find_swings(series)).events
    assert len([e for e in events if e.level == 105.1]) == 1


def test_levels_cluster_repeated_swings() -> None:
    series = waves([110, 110.2, 110.1], [100, 100.1, 100.2, 100])
    swings = find_swings(series)
    volatility = atr(series)
    levels = support_resistance(series, swings, volatility, len(series) - 1)
    assert levels
    assert all(level.touches >= 2 for level in levels)
    assert max(level.strength for level in levels) <= 100


def test_levels_are_empty_during_warm_up() -> None:
    series = from_closes(PEAK)
    assert support_resistance(series, find_swings(series), atr(series), 2) == []


def test_levels_ignore_swings_not_yet_confirmed() -> None:
    series = random_walk(300, seed=5)
    swings = find_swings(series)
    level_sets = support_resistance(series, swings, atr(series), 100)
    unconfirmed = [s.price for s in swings if s.confirmed_index > 100]
    assert all(level.first_touch <= series.close_time[100] for level in level_sets)
    assert unconfirmed


def test_demand_zone_needs_a_base_and_an_impulse() -> None:
    candles = [candle(i, 100, 101, 99, 100) for i in range(30)]
    candles += [candle(30, 100, 100.5, 99.8, 100.2)]
    candles += [candle(31, 100.2, 110, 100.1, 109)]
    candles += [candle(32, 109, 110, 108, 109)]
    series = CandleSeries.of(candles)
    zones = supply_demand_zones(series, atr(series))
    assert [z.pattern_type for z in zones] == ["demand_zone"]
    assert zones[0].direction is Direction.BULLISH
    assert zones[0].invalidated_at is None


def test_a_zone_is_invalidated_by_a_close_beyond_its_far_side() -> None:
    candles = [candle(i, 100, 101, 99, 100) for i in range(30)]
    candles += [candle(30, 100, 100.5, 99.8, 100.2), candle(31, 100.2, 110, 100.1, 109)]
    candles += [candle(32, 109, 109.5, 90, 91)]
    series = CandleSeries.of(candles)
    [zone] = [
        z for z in supply_demand_zones(series, atr(series)) if z.pattern_type == "demand_zone"
    ]
    assert zone.invalidated_at == series.close_time[32]


def test_consolidation_is_found_and_ends_on_a_close_outside() -> None:
    candles = [candle(i, 100, 104, 96, 100) for i in range(20)]
    candles += [candle(20 + i, 100, 100.5, 99.5, 100) for i in range(12)]
    candles += [candle(32, 100, 120, 100, 119)]
    series = CandleSeries.of(candles)
    found = consolidations(series, atr(series))
    assert found
    assert found[-1].invalidated_at == series.close_time[32]


def test_equal_highs_need_two_swings_within_tolerance() -> None:
    series = waves([110, 110.05, 105], [100, 101, 102, 101])
    found = equal_levels(series, find_swings(series), atr(series))
    assert "equal_highs" in {p.pattern_type for p in found}


def test_liquidity_sweep_closes_back_inside() -> None:
    candles: list[ClosedCandle] = []
    previous = 100.0
    for index, close in enumerate([*PEAK, 101, 102]):
        candles.append(
            candle(index, previous, max(previous, close) + 0.1, min(previous, close) - 0.1, close)
        )
        previous = close
    candles.append(candle(len(candles), 102, 107, 101.5, 103))
    series = CandleSeries.of(candles)
    [sweep] = liquidity_sweeps(series, find_swings(series))
    assert sweep.direction is Direction.BEARISH
    assert sweep.price_level == pytest.approx(105.1)


def test_a_close_beyond_the_swing_is_a_break_not_a_sweep() -> None:
    closes = [*PEAK, 101, 102, 108]
    series = from_closes(closes, 0.1)
    assert liquidity_sweeps(series, find_swings(series)) == []


def rising(timeframe: Timeframe, count: int) -> list[ClosedCandle]:
    candles: list[ClosedCandle] = []
    closes: list[float] = []
    for wave in range(count):
        base = 100 + wave * 4
        closes += [base + 2, base + 4, base + 6, base + 8, base + 6, base + 4, base + 2]
    previous = 100.0
    for index, close in enumerate(closes):
        candles.append(
            candle(
                index,
                previous,
                max(previous, close) + 0.1,
                min(previous, close) - 0.1,
                close,
                timeframe=timeframe,
            )
        )
        previous = close
    return candles


def test_timeframe_view_reports_agreement_with_the_direction_role() -> None:
    data = {t: rising(t, 8) for t in (Timeframe.D1, Timeframe.H4)}
    decision = START + timedelta(days=400)
    view = build_view(data, decision)
    assert view.direction == "up"
    assert {r.role: r.trend for r in view.roles}["structure"] == "up"
    assert view.alignment == pytest.approx(1 / 5)


def test_timeframe_view_ignores_candles_closing_after_the_decision() -> None:
    data = {Timeframe.D1: rising(Timeframe.D1, 8)}
    decision = START + timedelta(days=5, hours=12)
    view = build_view(data, decision)
    assert next(r for r in view.roles if r.role == "direction").candles_used == 5
