"""Market regimes on synthetic daily candles."""

from datetime import timedelta

import numpy as np

from tests.quant_data import candle, random_walk
from trading_intel.domain.candles import Timeframe
from trading_intel.market_structure.regime import RegimeView, volatility_percentiles
from trading_intel.technical_analysis.series import CandleSeries


def days(closes: list[float], wick: float = 1.0) -> CandleSeries:
    rows, previous = [], closes[0]
    for index, close in enumerate(closes):
        low, high = min(previous, close) - wick, max(previous, close) + wick
        rows.append(candle(index, previous, high, low, close, timeframe=Timeframe.D1))
        previous = close
    return CandleSeries.of(rows)


def test_a_steady_climb_is_trending() -> None:
    series = days([1000 + 10 * i for i in range(200)])
    assert RegimeView(series).at(series.close_time[-1]).trend == "trending"


def test_noise_around_a_level_is_ranging() -> None:
    rng = np.random.default_rng(3)
    series = days([1000 + float(rng.normal(0, 10)) for _ in range(200)])
    assert RegimeView(series).at(series.close_time[-1]).trend == "ranging"


def test_a_sudden_wide_swing_is_volatile_and_a_lull_is_calm() -> None:
    quiet = [1000 + (1 if i % 2 else -1) for i in range(200)]
    wild = days(quiet + [1000 + (60 if i % 2 else -60) for i in range(5)])
    assert RegimeView(wild).at(wild.close_time[-1]).volatility == "volatile"
    lull = days([1000 + (40 if i % 2 else -40) for i in range(200)] + [1000] * 40, wick=0.5)
    assert RegimeView(lull).at(lull.close_time[-1]).volatility == "calm"


def test_regimes_need_history_and_never_look_ahead() -> None:
    series = random_walk(400, seed=5, timeframe=Timeframe.D1)
    full = RegimeView(series)
    assert full.at(series.close_time[0] - timedelta(days=1)).trend == "unknown"
    assert full.at(series.close_time[10]).volatility == "unknown"  # Under 90 days of history.
    for end in (120, 250, 399):
        moment = series.close_time[end - 1]
        assert RegimeView(series.upto(end)).at(moment) == full.at(moment)


def test_percentiles_rank_each_day_against_its_own_trailing_year() -> None:
    series = random_walk(500, seed=8, timeframe=Timeframe.D1)
    ranks = volatility_percentiles(series)
    valid = ranks[~(ranks != ranks)]
    assert len(valid) > 300
    assert ((valid > 0) & (valid <= 100)).all()
