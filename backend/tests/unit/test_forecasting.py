"""Forecast summaries, the resampling baseline, scores, track records and Claude's facts.

All paths here are constructed test data, not model output or market data.
"""

from dataclasses import replace
from datetime import UTC, datetime

import numpy as np
import pytest

from tests.quant_data import random_walk
from trading_intel.domain.candles import Timeframe
from trading_intel.forecasting.evidence import LABEL, forecast_facts
from trading_intel.forecasting.paths import SampledPaths
from trading_intel.forecasting.scoring import Realized, crps, realized, score
from trading_intel.forecasting.summary import GRID, PathSummary, reach_share, summarise
from trading_intel.forecasting.time_machine import TimeMachineParameters, time_machine
from trading_intel.forecasting.track_record import MINIMUM_FORECASTS, track_record

AS_OF = datetime(2026, 1, 1, 23, 59, 59, 999000, tzinfo=UTC)


def paths(candles: list[list[list[float]]], last_close: float = 100.0) -> SampledPaths:
    return SampledPaths("test", Timeframe.H1, AS_OF, last_close, np.array(candles, dtype=float))


def uniform(low: float, high: float, share_higher: float = 0.5) -> PathSummary:
    """Percentiles spread evenly between two prices, for every measure."""
    grid = tuple(low + (high - low) * level for level in GRID)
    return PathSummary(30, 24, share_higher, grid, grid, grid, 0)


def test_paths_reject_wrong_shapes_and_impossible_prices() -> None:
    with pytest.raises(ValueError, match="shape"):
        paths([[[100.0, 101.0, 99.0]]])
    with pytest.raises(ValueError, match="positive"):
        paths([[[100.0, 101.0, 0.0, 100.0]]])
    with pytest.raises(ValueError, match="positive"):
        paths([[[100.0, float("nan"), 99.0, 100.0]]])


def test_summary_reads_extremes_over_all_four_prices() -> None:
    sampled = paths(
        [
            [[100, 102, 99, 101], [101, 103, 100, 104]],  # Second candle's high is below its close.
            [[100, 101, 97, 98], [98, 99, 96, 97]],
        ]
    )
    summary = summarise(sampled)
    assert summary.count == 2 and summary.horizon == 2
    assert summary.share_higher == 0.5
    assert summary.inconsistent_candles == 1
    assert summary.at("high", 99) == pytest.approx(101 + 3 * 0.99)  # Up to 104, the close.
    assert summary.at("low", 1) == pytest.approx(96 + 3 * 0.01)
    assert summary.at("close", 50) == pytest.approx(100.5)
    assert PathSummary.from_json(summary.as_json()) == summary


def test_reach_share_uses_highs_above_the_close_and_lows_below_it() -> None:
    summary = uniform(90.0, 110.0)
    assert reach_share(summary, 120.0, last_close=100.0) == 0.0
    assert reach_share(summary, 80.0, last_close=100.0) == 0.0
    assert reach_share(summary, 105.0, last_close=100.0) == pytest.approx(0.25)
    assert reach_share(summary, 95.0, last_close=100.0) == pytest.approx(0.25)


def test_time_machine_is_seeded_and_chains_real_candle_shapes() -> None:
    series = random_walk(300, seed=4)
    parameters = TimeMachineParameters(lookback=200, block=2, paths=50, seed=3)
    first = time_machine(series, 6, parameters)
    assert np.array_equal(first.candles, time_machine(series, 6, parameters).candles)
    other = time_machine(series, 6, TimeMachineParameters(lookback=200, paths=50, seed=4))
    assert not np.array_equal(first.candles, other.candles)

    candles = first.candles
    assert first.as_of == series.close_time[-1] and first.last_close == series.close[-1]
    assert np.allclose(candles[:, 0, 0], series.close[-1])
    assert np.allclose(
        candles[:, 1:, 0], candles[:, :-1, 3]
    )  # Each candle opens at the last close.
    recent = series.window(100, 300)
    real = np.stack([recent.high, recent.low, recent.close], axis=1) / recent.open[:, None]
    drawn = candles[..., 1:].reshape(-1, 3) / candles[..., 0].reshape(-1, 1)
    assert all(np.isclose(real, shape).all(axis=1).any() for shape in drawn)


def test_time_machine_ignores_candles_before_its_lookback() -> None:
    series = random_walk(300, seed=4)
    parameters = TimeMachineParameters(lookback=200, paths=20)
    changed = random_walk(300, seed=9)
    # Same last 200 candle shapes and close, different early history.
    spliced = replace(series, open=np.concatenate([changed.open[:100], series.open[100:]]))
    assert np.array_equal(
        time_machine(series, 4, parameters).candles, time_machine(spliced, 4, parameters).candles
    )
    with pytest.raises(ValueError, match="needs 200 candles"):
        time_machine(series.upto(150), 4, parameters)


def test_realized_takes_the_first_horizon_candles_and_needs_all_of_them() -> None:
    after = random_walk(30, seed=2)
    outcome = realized(after, 24)
    window = after.window(0, 24)
    assert outcome == Realized(window.high.max(), window.low.min(), window.close[-1])
    with pytest.raises(ValueError, match="24 continuous candles"):
        realized(after.upto(20), 24)


def test_crps_of_a_certain_forecast_is_the_distance_to_the_outcome() -> None:
    certain = tuple(100.0 for _ in GRID)
    assert crps(certain, 103.0) == pytest.approx(3.0)
    assert crps(certain, 96.0) == pytest.approx(4.0)
    spread = uniform(90.0, 110.0).close
    assert crps(spread, 100.0) < crps(spread, 109.0)


def test_score_compares_one_forecast_with_what_happened() -> None:
    result = score(uniform(90.0, 110.0, share_higher=0.8), Realized(104.0, 95.0, 102.0), 100.0)
    assert result.ended_higher
    assert result.brier == pytest.approx(0.04)
    assert result.levels["close"] == pytest.approx(0.6)
    assert result.inside_band == {"high": True, "low": True, "close": True}
    missed = score(uniform(90.0, 110.0), Realized(120.0, 99.0, 115.0), 100.0)
    assert missed.levels["close"] == 1.0 and not missed.inside_band["close"]
    assert missed.close_crps_pct > result.close_crps_pct


def pair(model_share: float, baseline_share: float, up: bool) -> tuple:
    close = 105.0 if up else 95.0
    outcome = Realized(max(close, 100.0) + 1, min(close, 100.0) - 1, close)
    model = uniform(close - 1, close + 1, model_share) if model_share else uniform(80, 120, 0.5)
    return score(model, outcome, 100.0), score(uniform(80, 120, baseline_share), outcome, 100.0)


def test_track_record_needs_enough_forecasts_before_judging_the_model() -> None:
    assert track_record([]).status == "too few forecasts"
    better = [pair(0.9 if i % 2 else 0.1, 0.5, up=bool(i % 2)) for i in range(MINIMUM_FORECASTS)]
    assert track_record(better[:-1]).status == "too few forecasts"
    record = track_record(better)
    assert record.status == "better than baseline"
    assert record.brier_difference is not None and record.brier_difference.high < 0
    assert record == track_record(better)  # Seeded bootstrap.
    assert record.model is not None
    assert sum(b.count for b in record.model.reliability) == MINIMUM_FORECASTS
    assert sum(record.model.close_level_counts) == MINIMUM_FORECASTS


def test_track_record_flags_a_model_worse_than_the_baseline() -> None:
    worse = [pair(0.1 if i % 2 else 0.9, 0.5, up=bool(i % 2)) for i in range(MINIMUM_FORECASTS)]
    assert track_record(worse).status == "worse than baseline"
    assert track_record(worse).facts()["brier"]["model"] > 0.25


def test_facts_are_in_atr_from_the_last_close_and_labelled_unvalidated() -> None:
    model = uniform(98.0, 104.0, share_higher=0.87)
    facts = forecast_facts(
        model,
        uniform(97.0, 103.0, share_higher=0.47),
        model_name="NeoQuasar/Kronos-small",
        timeframe=Timeframe.H1,
        as_of=AS_OF,
        last_close=100.0,
        atr=0.5,
        record=track_record([]),
        levels=[("L4", 102.5), ("L2", 98.5)],
    )
    assert facts["label"] == LABEL
    assert facts["forecast"]["share_ending_higher"] == 0.87
    assert facts["baseline"]["share_ending_higher"] == 0.47
    assert facts["forecast"]["close_atr"]["p50"] == pytest.approx(2.0)
    assert facts["paths"] == {"model": 30, "baseline": 30}
    assert facts["levels"][0] == {"id": "L4", "reached_share": {"model": 0.25, "baseline": 0.08}}
    assert facts["track_record"] == {"resolved": 0, "status": "too few forecasts"}
    with pytest.raises(ValueError, match="ATR"):
        forecast_facts(
            model,
            model,
            model_name="m",
            timeframe=Timeframe.H1,
            as_of=AS_OF,
            last_close=100.0,
            atr=0.0,
            record=track_record([]),
        )
