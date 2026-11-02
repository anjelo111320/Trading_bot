"""Volume indicators. Definitions are in docs/25-PATTERN-RULES.md."""

import numpy as np

from trading_intel.technical_analysis.series import CandleSeries, FloatArray, empty_like
from trading_intel.technical_analysis.smoothing import sma

SPIKE_RATIO = 2.0


def relative_volume(volume: FloatArray, period: int = 20) -> FloatArray:
    """Volume over the mean of the candles before it, so a spike cannot dilute itself."""
    output = empty_like(volume)
    mean = sma(volume, period)
    with np.errstate(divide="ignore", invalid="ignore"):
        output[1:] = volume[1:] / mean[:-1]
    return np.where(np.isfinite(output), output, np.nan)


def volume_spikes(volume: FloatArray, period: int = 20) -> FloatArray:
    """1 on a spike, 0 otherwise, and empty during warm-up."""
    ratio = relative_volume(volume, period)
    return np.where(np.isnan(ratio), np.nan, (ratio >= SPIKE_RATIO).astype(np.float64))


def on_balance_volume(series: CandleSeries) -> FloatArray:
    signs = np.zeros_like(series.close)
    signs[1:] = np.sign(np.diff(series.close))
    return np.cumsum(signs * series.volume)


def volume_delta(series: CandleSeries) -> FloatArray:
    """Empty where the provider gave no taker data, rather than being guessed."""
    return 2.0 * series.taker_buy_volume - series.volume
