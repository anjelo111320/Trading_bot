"""Market regime: how strongly price trends, and how volatile it is against its own year.

Labels are known at each candle's close, from that candle and earlier ones only. They let
history be summarised by market condition, so Claude reads measured base rates for the
current regime instead of raw history (D036).
"""

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal

import numpy as np

from trading_intel.technical_analysis.series import CandleSeries, FloatArray
from trading_intel.technical_analysis.trend import adx
from trading_intel.technical_analysis.volatility import atr

TRENDING_ADX: Final = 25.0  # Common practitioner bands: below 20 ranging, above 25 trending.
RANGING_ADX: Final = 20.0
VOLATILITY_WINDOW: Final = 365  # Daily candles: one year of crypto, which trades every day.
MIN_HISTORY: Final = 90
CALM_PERCENTILE: Final = 25.0
VOLATILE_PERCENTILE: Final = 75.0

TrendRegime = Literal["trending", "transition", "ranging", "unknown"]
VolatilityRegime = Literal["calm", "normal", "volatile", "unknown"]


@dataclass(frozen=True)
class Regime:
    trend: TrendRegime
    volatility: VolatilityRegime
    adx: float | None
    volatility_percentile: float | None

    @property
    def label(self) -> str:
        return f"{self.trend}, {self.volatility}"


def volatility_percentiles(series: CandleSeries, window: int = VOLATILITY_WINDOW) -> FloatArray:
    """ATR as a share of price, ranked against the trailing window that ends at each candle."""
    share = atr(series) / series.close
    output = np.full(len(series), np.nan)
    for index in range(len(series)):
        history = share[max(index - window + 1, 0) : index + 1]
        history = history[~np.isnan(history)]
        if len(history) >= MIN_HISTORY and not np.isnan(share[index]):
            output[index] = 100.0 * float(np.mean(history <= share[index]))
    return output


def _trend(value: float) -> TrendRegime:
    if value != value:
        return "unknown"
    if value >= TRENDING_ADX:
        return "trending"
    return "ranging" if value < RANGING_ADX else "transition"


def _volatility(value: float) -> VolatilityRegime:
    if value != value:
        return "unknown"
    if value <= CALM_PERCENTILE:
        return "calm"
    return "volatile" if value >= VOLATILE_PERCENTILE else "normal"


class RegimeView:
    """Regimes of a daily series, read as of a moment: the last candle closed by then."""

    def __init__(self, series: CandleSeries) -> None:
        self._close_times = list(series.close_time)
        self._adx = adx(series).adx
        self._percentile = volatility_percentiles(series)

    def at(self, moment: datetime) -> Regime:
        position = bisect_right(self._close_times, moment) - 1
        if position < 0:
            return Regime("unknown", "unknown", None, None)
        strength, rank = float(self._adx[position]), float(self._percentile[position])
        return Regime(
            trend=_trend(strength),
            volatility=_volatility(rank),
            adx=None if strength != strength else round(strength, 1),
            volatility_percentile=None if rank != rank else round(rank, 1),
        )
