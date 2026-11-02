"""Volatility indicators. Definitions are in docs/25-PATTERN-RULES.md."""

from dataclasses import dataclass

import numpy as np

from trading_intel.domain.candles import Timeframe
from trading_intel.technical_analysis.series import (
    SECONDS_PER_YEAR,
    CandleSeries,
    FloatArray,
    empty_like,
)
from trading_intel.technical_analysis.smoothing import ema, rolling_std, sma, wilder


def true_range(series: CandleSeries) -> FloatArray:
    """Empty on the first candle, which has no previous close."""
    output = empty_like(series.close)
    previous = series.close[:-1]
    output[1:] = np.maximum.reduce(
        [
            series.high[1:] - series.low[1:],
            np.abs(series.high[1:] - previous),
            np.abs(series.low[1:] - previous),
        ]
    )
    return output


def atr(series: CandleSeries, period: int = 14) -> FloatArray:
    return wilder(true_range(series), period)


@dataclass(frozen=True)
class Bands:
    upper: FloatArray
    middle: FloatArray
    lower: FloatArray


def bollinger(series: CandleSeries, period: int = 20, width: float = 2.0) -> Bands:
    middle = sma(series.close, period)
    deviation = rolling_std(series.close, period, sample=False)
    return Bands(middle + width * deviation, middle, middle - width * deviation)


def keltner(
    series: CandleSeries, ema_period: int = 20, atr_period: int = 10, width: float = 2.0
) -> Bands:
    middle = ema(series.close, ema_period)
    channel = atr(series, atr_period)
    return Bands(middle + width * channel, middle, middle - width * channel)


def historical_volatility(close: FloatArray, timeframe: Timeframe, period: int = 20) -> FloatArray:
    """Annualised, on a 365-day year because crypto trades every day."""
    returns = empty_like(close)
    returns[1:] = np.log(close[1:] / close[:-1])
    scale = float(np.sqrt(SECONDS_PER_YEAR / timeframe.seconds))
    deviation: FloatArray = rolling_std(returns, period, sample=True)
    return deviation * scale
