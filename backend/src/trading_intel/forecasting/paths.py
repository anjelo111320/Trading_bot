"""Sampled future candle paths, from a forecasting model or a resampling baseline.

A path is one possible future, not a prediction to trade on. Path prices are floats because
they are samples. Market prices stay Decimal everywhere else.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Final

import numpy as np

from trading_intel.domain.candles import Timeframe
from trading_intel.technical_analysis.series import FloatArray

OPEN: Final = 0
HIGH: Final = 1
LOW: Final = 2
CLOSE: Final = 3


@dataclass(frozen=True, eq=False)
class SampledPaths:
    source: str
    timeframe: Timeframe
    as_of: datetime  # Close time of the last input candle.
    last_close: float
    candles: FloatArray  # Shape (paths, horizon, 4): open, high, low, close.

    def __post_init__(self) -> None:
        shape = self.candles.shape
        if len(shape) != 3 or shape[0] < 1 or shape[1] < 1 or shape[2] != 4:
            raise ValueError("paths need the shape (paths, horizon, 4)")
        if not np.isfinite(self.candles).all() or (self.candles <= 0).any():
            raise ValueError("path prices must be finite and positive")
        if not self.last_close > 0:
            raise ValueError("the last close must be positive")

    @property
    def count(self) -> int:
        return int(self.candles.shape[0])

    @property
    def horizon(self) -> int:
        return int(self.candles.shape[1])
