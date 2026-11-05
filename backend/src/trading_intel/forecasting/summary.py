"""What a set of sampled paths says, as percentiles that can be stored and scored later.

The model and the baseline are summarised the same way, so their scores are comparable.
"""

from dataclasses import dataclass
from typing import Any, Final, Literal

import numpy as np

from trading_intel.forecasting.paths import CLOSE, HIGH, LOW, OPEN, SampledPaths
from trading_intel.technical_analysis.series import FloatArray

GRID: Final = tuple(k / 100 for k in range(1, 100))  # Percentiles 1 to 99.
BAND: Final = (10, 50, 90)  # Percentiles shown to Claude and used for band coverage.

Measure = Literal["high", "low", "close"]


@dataclass(frozen=True)
class PathSummary:
    count: int
    horizon: int
    share_higher: float  # Share of paths whose final close is above the last close.
    high: tuple[float, ...]  # Percentiles 1 to 99 of the highest price each path reaches.
    low: tuple[float, ...]  # Percentiles 1 to 99 of the lowest price each path reaches.
    close: tuple[float, ...]  # Percentiles 1 to 99 of the final close.
    inconsistent_candles: int  # Sampled candles whose high or low did not contain open and close.

    def percentiles(self, measure: Measure) -> tuple[float, ...]:
        values: tuple[float, ...] = getattr(self, measure)
        return values

    def at(self, measure: Measure, percentile: int) -> float:
        return self.percentiles(measure)[percentile - 1]

    def as_json(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "horizon": self.horizon,
            "share_higher": self.share_higher,
            "high": list(self.high),
            "low": list(self.low),
            "close": list(self.close),
            "inconsistent_candles": self.inconsistent_candles,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> PathSummary:
        return cls(
            count=int(data["count"]),
            horizon=int(data["horizon"]),
            share_higher=float(data["share_higher"]),
            high=tuple(float(v) for v in data["high"]),
            low=tuple(float(v) for v in data["low"]),
            close=tuple(float(v) for v in data["close"]),
            inconsistent_candles=int(data["inconsistent_candles"]),
        )


def extremes(paths: SampledPaths) -> tuple[FloatArray, FloatArray, FloatArray]:
    """Each path's highest price, lowest price and final close.

    A model can sample a candle whose high is below its own open or close. The extremes are
    therefore taken over all four prices, never only the high and low columns.
    """
    candles = paths.candles
    return candles.max(axis=(1, 2)), candles.min(axis=(1, 2)), candles[:, -1, CLOSE]


def summarise(paths: SampledPaths) -> PathSummary:
    highs, lows, closes = extremes(paths)
    candles = paths.candles
    upper = np.maximum(candles[..., OPEN], candles[..., CLOSE])
    lower = np.minimum(candles[..., OPEN], candles[..., CLOSE])
    inconsistent = (candles[..., HIGH] < upper) | (candles[..., LOW] > lower)
    return PathSummary(
        count=paths.count,
        horizon=paths.horizon,
        share_higher=float(np.mean(closes > paths.last_close)),
        high=_percentiles(highs),
        low=_percentiles(lows),
        close=_percentiles(closes),
        inconsistent_candles=int(inconsistent.sum()),
    )


def quantile_level(percentiles: tuple[float, ...], value: float) -> float:
    """Where a value falls among the percentiles, from 0 to 1."""
    return float(np.interp(value, percentiles, GRID, left=0.0, right=1.0))


def reach_share(summary: PathSummary, price: float, last_close: float) -> float:
    """Share of paths that reach a price within the horizon, read from the percentiles.

    A price at or above the last close is reached when a path's high gets there, and a price
    below it when a path's low does.
    """
    if price >= last_close:
        return 1.0 - quantile_level(summary.high, price)
    return quantile_level(summary.low, price)


def _percentiles(values: FloatArray) -> tuple[float, ...]:
    return tuple(float(v) for v in np.quantile(values, GRID))
