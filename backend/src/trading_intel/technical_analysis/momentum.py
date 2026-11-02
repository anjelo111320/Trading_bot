"""Momentum indicators. Definitions are in docs/25-PATTERN-RULES.md."""

from dataclasses import dataclass

import numpy as np

from trading_intel.technical_analysis.series import CandleSeries, FloatArray, empty_like
from trading_intel.technical_analysis.smoothing import ema, rolling_extreme, sma, wilder
from trading_intel.technical_analysis.trend import typical_price

FLAT_RSI = 50.0
CCI_CONSTANT = 0.015


def rsi(close: FloatArray, period: int = 14) -> FloatArray:
    """Wilder RSI. A completely flat history has no direction, so it reads 50."""
    change = empty_like(close)
    change[1:] = np.diff(close)
    gains = wilder(np.where(np.isnan(change), np.nan, np.maximum(change, 0.0)), period)
    losses = wilder(np.where(np.isnan(change), np.nan, np.maximum(-change, 0.0)), period)
    total = gains + losses
    with np.errstate(divide="ignore", invalid="ignore"):
        value = 100.0 * gains / total
    return np.where(total == 0, FLAT_RSI, value)


@dataclass(frozen=True)
class Macd:
    line: FloatArray
    signal: FloatArray
    histogram: FloatArray


def macd(close: FloatArray, fast: int = 12, slow: int = 26, signal: int = 9) -> Macd:
    line = ema(close, fast) - ema(close, slow)
    smoothed = ema(line, signal)
    return Macd(line, smoothed, line - smoothed)


@dataclass(frozen=True)
class StochasticRsi:
    k: FloatArray
    d: FloatArray


def stochastic_rsi(
    close: FloatArray,
    rsi_period: int = 14,
    stoch_period: int = 14,
    k_smooth: int = 3,
    d_smooth: int = 3,
) -> StochasticRsi:
    value = rsi(close, rsi_period)
    highest = rolling_extreme(value, stoch_period, highest=True)
    lowest = rolling_extreme(value, stoch_period, highest=False)
    span = highest - lowest
    with np.errstate(divide="ignore", invalid="ignore"):
        raw = 100.0 * (value - lowest) / span
    raw = np.where(span == 0, 0.0, raw)
    k = sma(raw, k_smooth)
    return StochasticRsi(k, sma(k, d_smooth))


def cci(series: CandleSeries, period: int = 20) -> FloatArray:
    typical = typical_price(series)
    output = empty_like(typical)
    if len(typical) < period:
        return output
    windows = np.lib.stride_tricks.sliding_window_view(typical, period)
    means = windows.mean(axis=1)
    deviation = np.abs(windows - means[:, None]).mean(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        output[period - 1 :] = (typical[period - 1 :] - means) / (CCI_CONSTANT * deviation)
    return np.where(np.isfinite(output) | np.isnan(output), output, 0.0)


def rate_of_change(close: FloatArray, period: int = 10) -> FloatArray:
    output = empty_like(close)
    output[period:] = 100.0 * (close[period:] / close[:-period] - 1.0)
    return output
