"""Compute the full indicator set. The same code runs live and in backtests."""

import math
from typing import Final

import numpy as np

from trading_intel.technical_analysis.momentum import (
    cci,
    macd,
    rate_of_change,
    rsi,
    stochastic_rsi,
)
from trading_intel.technical_analysis.series import CandleSeries, FloatArray
from trading_intel.technical_analysis.smoothing import ema, sma
from trading_intel.technical_analysis.trend import adx, vwap
from trading_intel.technical_analysis.volatility import (
    atr,
    bollinger,
    historical_volatility,
    keltner,
)
from trading_intel.technical_analysis.volume import (
    on_balance_volume,
    relative_volume,
    volume_delta,
    volume_spikes,
)

FEATURE_SET_VERSION: Final = "1"


def compute_indicators(series: CandleSeries) -> dict[str, FloatArray]:
    close = series.close
    moving = {f"ema_{period}": ema(close, period) for period in (9, 20, 50, 100, 200)}
    moving |= {f"sma_{period}": sma(close, period) for period in (50, 200)}
    direction = adx(series)
    line = macd(close)
    stoch = stochastic_rsi(close)
    bands = bollinger(series)
    channel = keltner(series)
    return {
        **moving,
        "vwap": vwap(series),
        "adx": direction.adx,
        "plus_di": direction.plus_di,
        "minus_di": direction.minus_di,
        "rsi": rsi(close),
        "macd": line.line,
        "macd_signal": line.signal,
        "macd_histogram": line.histogram,
        "stoch_rsi_k": stoch.k,
        "stoch_rsi_d": stoch.d,
        "cci": cci(series),
        "roc": rate_of_change(close),
        "atr": atr(series),
        "bollinger_upper": bands.upper,
        "bollinger_middle": bands.middle,
        "bollinger_lower": bands.lower,
        "keltner_upper": channel.upper,
        "keltner_middle": channel.middle,
        "keltner_lower": channel.lower,
        "historical_volatility": historical_volatility(close, series.timeframe),
        "volume_sma": sma(series.volume, 20),
        "relative_volume": relative_volume(series.volume),
        "volume_spike": volume_spikes(series.volume),
        "obv": on_balance_volume(series),
        "volume_delta": volume_delta(series),
    }


def values_at(indicators: dict[str, FloatArray], index: int) -> dict[str, float | None]:
    """One candle's values for storage. A warm-up value is None, never a number."""
    result: dict[str, float | None] = {}
    for name, values in indicators.items():
        value = float(values[index])
        result[name] = None if math.isnan(value) or np.isinf(value) else value
    return result
