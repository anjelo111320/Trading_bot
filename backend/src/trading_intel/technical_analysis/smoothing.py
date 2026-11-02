"""Moving averages, which skip leading NaN so they can be chained."""

import numpy as np

from trading_intel.technical_analysis.series import FloatArray, empty_like


def _first_valid(values: FloatArray) -> int | None:
    valid = np.flatnonzero(~np.isnan(values))
    return int(valid[0]) if valid.size else None


def sma(values: FloatArray, period: int) -> FloatArray:
    output = empty_like(values)
    first = _first_valid(values)
    if first is None or len(values) - first < period:
        return output
    usable = values[first:]
    windows = np.lib.stride_tricks.sliding_window_view(usable, period)
    output[first + period - 1 :] = windows.mean(axis=1)
    return output


def _recursive(values: FloatArray, period: int, alpha: float) -> FloatArray:
    output = empty_like(values)
    first = _first_valid(values)
    if first is None or len(values) - first < period:
        return output
    start = first + period - 1
    current = float(values[first : start + 1].mean())
    output[start] = current
    for index in range(start + 1, len(values)):
        current += alpha * (float(values[index]) - current)
        output[index] = current
    return output


def ema(values: FloatArray, period: int) -> FloatArray:
    """Seeded with the SMA of the first `period` values."""
    return _recursive(values, period, 2.0 / (period + 1))


def wilder(values: FloatArray, period: int) -> FloatArray:
    """Wilder's smoothing: an EMA with alpha = 1 / period."""
    return _recursive(values, period, 1.0 / period)


def rolling_std(values: FloatArray, period: int, *, sample: bool) -> FloatArray:
    output = empty_like(values)
    first = _first_valid(values)
    if first is None or len(values) - first < period:
        return output
    windows = np.lib.stride_tricks.sliding_window_view(values[first:], period)
    output[first + period - 1 :] = windows.std(axis=1, ddof=1 if sample else 0)
    return output


def rolling_extreme(values: FloatArray, period: int, *, highest: bool) -> FloatArray:
    output = empty_like(values)
    first = _first_valid(values)
    if first is None or len(values) - first < period:
        return output
    windows = np.lib.stride_tricks.sliding_window_view(values[first:], period)
    extreme = windows.max(axis=1) if highest else windows.min(axis=1)
    output[first + period - 1 :] = extreme
    return output
