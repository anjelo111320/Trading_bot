"""Indicators against hand calculations and against TA-Lib, the trusted reference."""

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pytest
import talib

from tests.fakes import make_candle
from tests.quant_data import random_walk
from trading_intel.domain.candles import ClosedCandle, Timeframe
from trading_intel.technical_analysis import momentum, trend, volatility, volume
from trading_intel.technical_analysis.pipeline import compute_indicators, values_at
from trading_intel.technical_analysis.series import CandleSeries
from trading_intel.technical_analysis.smoothing import ema, sma, wilder

SERIES = random_walk(1500, seed=11)
# Recursive indicators forget their different seeds after enough candles, so compare late values.
SETTLED = 700
TOLERANCE = 1e-7


def close_to_reference(ours: np.ndarray, reference: np.ndarray, start: int = SETTLED) -> None:
    np.testing.assert_allclose(ours[start:], reference[start:], rtol=TOLERANCE, atol=1e-7)


def test_sma_by_hand() -> None:
    values = np.array([1.0, 2.0, 3.0, 4.0])
    result = sma(values, 2)
    assert math.isnan(result[0])
    assert result[1:].tolist() == [1.5, 2.5, 3.5]


def test_ema_by_hand() -> None:
    values = np.array([2.0, 4.0, 6.0, 8.0])
    result = ema(values, 3)  # Seed (2+4+6)/3 = 4, alpha 0.5, next (8-4)*0.5+4 = 6.
    assert result[2] == 4.0
    assert result[3] == 6.0


def test_wilder_by_hand() -> None:
    result = wilder(np.array([1.0, 2.0, 3.0, 7.0]), 3)  # Seed 2, next 2+(7-2)/3.
    assert result[3] == pytest.approx(2 + 5 / 3)


def test_rsi_of_a_flat_market_is_neutral() -> None:
    assert momentum.rsi(np.full(30, 100.0))[-1] == 50.0


def test_rsi_of_only_gains_is_100() -> None:
    assert momentum.rsi(np.arange(1.0, 40.0))[-1] == 100.0


def test_short_input_gives_empty_values_not_estimates() -> None:
    assert np.isnan(ema(np.array([1.0, 2.0]), 20)).all()
    assert np.isnan(momentum.rsi(np.array([1.0, 2.0]), 14)).all()


@pytest.mark.parametrize("period", [9, 20, 50, 100, 200])
def test_ema_matches_ta_lib(period: int) -> None:
    close_to_reference(ema(SERIES.close, period), talib.EMA(SERIES.close, period))


@pytest.mark.parametrize("period", [50, 200])
def test_sma_matches_ta_lib(period: int) -> None:
    close_to_reference(sma(SERIES.close, period), talib.SMA(SERIES.close, period), 200)


def test_rsi_matches_ta_lib() -> None:
    close_to_reference(momentum.rsi(SERIES.close), talib.RSI(SERIES.close, 14))


def test_macd_matches_ta_lib() -> None:
    ours = momentum.macd(SERIES.close)
    line, signal, histogram = talib.MACD(SERIES.close)
    close_to_reference(ours.line, line)
    close_to_reference(ours.signal, signal)
    close_to_reference(ours.histogram, histogram)


def test_cci_matches_ta_lib() -> None:
    reference = talib.CCI(SERIES.high, SERIES.low, SERIES.close, 20)
    close_to_reference(momentum.cci(SERIES), reference, 100)


def test_rate_of_change_matches_ta_lib() -> None:
    close_to_reference(momentum.rate_of_change(SERIES.close), talib.ROC(SERIES.close, 10), 20)


def test_atr_matches_ta_lib() -> None:
    reference = talib.ATR(SERIES.high, SERIES.low, SERIES.close, 14)
    close_to_reference(volatility.atr(SERIES), reference)


def test_true_range_matches_ta_lib() -> None:
    reference = talib.TRANGE(SERIES.high, SERIES.low, SERIES.close)
    close_to_reference(volatility.true_range(SERIES), reference, 1)


def test_adx_and_directional_indexes_match_ta_lib() -> None:
    ours = trend.adx(SERIES)
    high, low, close = SERIES.high, SERIES.low, SERIES.close
    close_to_reference(ours.adx, talib.ADX(high, low, close, 14))
    close_to_reference(ours.plus_di, talib.PLUS_DI(high, low, close, 14))
    close_to_reference(ours.minus_di, talib.MINUS_DI(high, low, close, 14))


def test_bollinger_matches_ta_lib() -> None:
    upper, middle, lower = talib.BBANDS(SERIES.close, 20, 2, 2)
    ours = volatility.bollinger(SERIES)
    close_to_reference(ours.upper, upper, 100)
    close_to_reference(ours.middle, middle, 100)
    close_to_reference(ours.lower, lower, 100)


def test_stochastic_rsi_matches_ta_lib_raw_line() -> None:
    fast_k, _ = talib.STOCHRSI(SERIES.close, 14, 14, 1)
    ours = momentum.stochastic_rsi(SERIES.close, k_smooth=1)
    close_to_reference(ours.k, fast_k)


def test_obv_moves_like_ta_lib() -> None:
    """TA-Lib starts from the first volume, so only the changes are comparable."""
    ours = np.diff(volume.on_balance_volume(SERIES))
    reference = np.diff(talib.OBV(SERIES.close, SERIES.volume))
    np.testing.assert_allclose(ours, reference)


def test_keltner_is_ema_plus_atr() -> None:
    bands = volatility.keltner(SERIES)
    expected = ema(SERIES.close, 20) + 2 * volatility.atr(SERIES, 10)
    close_to_reference(bands.upper, expected, 50)


def test_historical_volatility_by_hand() -> None:
    close = np.exp(np.cumsum(np.array([0.0, 0.01, -0.01] * 8)))
    result = volatility.historical_volatility(close, Timeframe.D1, period=20)
    returns = np.diff(np.log(close))[-20:]
    assert result[-1] == pytest.approx(returns.std(ddof=1) * math.sqrt(365))


def day_series(volumes: list[str]) -> CandleSeries:
    start = datetime(2026, 1, 1, 22, tzinfo=UTC)
    candles = [
        make_candle(1, 1, Timeframe.H1, start + timedelta(hours=i), volume=Decimal(v))
        for i, v in enumerate(volumes)
    ]
    return CandleSeries.of(candles)


def test_vwap_resets_at_midnight_utc() -> None:
    series = day_series(["1", "3", "2"])
    result = trend.vwap(series)
    # All typical prices are equal here, so VWAP equals it until the reset changes nothing.
    typical = (110 + 90 + 105) / 3
    assert result.tolist() == pytest.approx([typical] * 3)


def test_vwap_is_empty_until_volume_trades() -> None:
    assert math.isnan(trend.vwap(day_series(["0", "1"]))[0])


def test_a_spike_does_not_dilute_its_own_baseline() -> None:
    values = np.array([1.0] * 20 + [5.0])
    assert volume.relative_volume(values)[-1] == 5.0
    assert volume.volume_spikes(values)[-1] == 1.0


def test_missing_taker_data_stays_empty() -> None:
    assert np.isnan(volume.volume_delta(day_series(["1"]))).all()


def test_volume_delta_uses_taker_data() -> None:
    assert volume.volume_delta(SERIES)[0] == 2 * SERIES.taker_buy_volume[0] - SERIES.volume[0]


def test_pipeline_is_deterministic() -> None:
    first = compute_indicators(SERIES)
    second = compute_indicators(SERIES)
    for name, values in first.items():
        np.testing.assert_array_equal(values, second[name], err_msg=name)


def test_pipeline_covers_every_required_indicator() -> None:
    names = set(compute_indicators(SERIES))
    assert {
        "ema_9", "ema_20", "ema_50", "ema_100", "ema_200", "sma_50", "sma_200", "vwap", "adx",
        "rsi", "macd", "stoch_rsi_k", "cci", "roc", "atr", "bollinger_upper",
        "historical_volatility", "keltner_upper", "volume_sma", "relative_volume",
        "volume_spike", "obv", "volume_delta",
    } <= names  # fmt: skip


def test_warm_up_values_are_stored_as_none() -> None:
    values = values_at(compute_indicators(SERIES), 0)
    assert values["ema_200"] is None
    assert values["obv"] is not None


def test_series_refuses_mixed_markets() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    candles: list[ClosedCandle] = [
        make_candle(1, 1, Timeframe.M1, now),
        make_candle(1, 2, Timeframe.M1, now + timedelta(minutes=1)),
    ]
    with pytest.raises(ValueError, match="one provider"):
        CandleSeries.of(candles)


def test_series_refuses_unordered_candles() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    candles = [
        make_candle(1, 1, Timeframe.M1, now + timedelta(minutes=1)),
        make_candle(1, 1, Timeframe.M1, now),
    ]
    with pytest.raises(ValueError, match="ascending"):
        CandleSeries.of(candles)


def test_series_reports_a_missing_candle() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    candles = [
        make_candle(1, 1, Timeframe.M1, now),
        make_candle(1, 1, Timeframe.M1, now + timedelta(minutes=2)),
    ]
    assert not CandleSeries.of(candles).is_continuous
