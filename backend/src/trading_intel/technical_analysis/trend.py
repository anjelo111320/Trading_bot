"""Trend indicators. Definitions are in docs/25-PATTERN-RULES.md."""

from dataclasses import dataclass

import numpy as np

from trading_intel.technical_analysis.series import CandleSeries, FloatArray, empty_like
from trading_intel.technical_analysis.smoothing import wilder
from trading_intel.technical_analysis.volatility import true_range


def typical_price(series: CandleSeries) -> FloatArray:
    return (series.high + series.low + series.close) / 3.0


def vwap(series: CandleSeries) -> FloatArray:
    """Anchored at 00:00 UTC. Empty until volume has traded in the session."""
    output = empty_like(series.close)
    weighted = series.volume * typical_price(series)
    total_value = total_volume = 0.0
    day = None
    for index, at in enumerate(series.open_time):
        if at.date() != day:
            day = at.date()
            total_value = total_volume = 0.0
        total_value += float(weighted[index])
        total_volume += float(series.volume[index])
        if total_volume > 0:
            output[index] = total_value / total_volume
    return output


@dataclass(frozen=True)
class DirectionalIndex:
    adx: FloatArray
    plus_di: FloatArray
    minus_di: FloatArray


def adx(series: CandleSeries, period: int = 14) -> DirectionalIndex:
    up = empty_like(series.close)
    down = empty_like(series.close)
    rise = series.high[1:] - series.high[:-1]
    fall = series.low[:-1] - series.low[1:]
    up[1:] = np.where((rise > fall) & (rise > 0), rise, 0.0)
    down[1:] = np.where((fall > rise) & (fall > 0), fall, 0.0)

    smooth_tr = wilder(true_range(series), period)
    with np.errstate(divide="ignore", invalid="ignore"):
        plus = 100.0 * wilder(up, period) / smooth_tr
        minus = 100.0 * wilder(down, period) / smooth_tr
        total = plus + minus
        dx = np.where(total > 0, 100.0 * np.abs(plus - minus) / total, 0.0)
    dx[np.isnan(plus) | np.isnan(minus)] = np.nan
    return DirectionalIndex(wilder(dx, period), plus, minus)
