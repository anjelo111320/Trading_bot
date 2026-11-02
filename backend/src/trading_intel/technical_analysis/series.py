"""Candle arrays for the numeric engine.

Only ClosedCandle can enter, so a forming candle cannot reach an indicator. Floats are
allowed from here inward (D015). Empty results are NaN, never an estimate.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise
from typing import Final

import numpy as np
import numpy.typing as npt

from trading_intel.domain.candles import ClosedCandle, Timeframe

FloatArray = npt.NDArray[np.float64]

SECONDS_PER_YEAR: Final = 365 * 86_400


def empty_like(values: FloatArray) -> FloatArray:
    return np.full(values.shape, np.nan, dtype=np.float64)


@dataclass(frozen=True)
class CandleSeries:
    timeframe: Timeframe
    open_time: tuple[datetime, ...]
    close_time: tuple[datetime, ...]
    open: FloatArray
    high: FloatArray
    low: FloatArray
    close: FloatArray
    volume: FloatArray
    taker_buy_volume: FloatArray
    is_continuous: bool

    def __len__(self) -> int:
        return len(self.close)

    @classmethod
    def of(cls, candles: Sequence[ClosedCandle]) -> CandleSeries:
        if not candles:
            raise ValueError("a series needs at least one candle")
        first = candles[0]
        same_market = all(
            c.provider_id == first.provider_id
            and c.instrument_id == first.instrument_id
            and c.timeframe is first.timeframe
            for c in candles
        )
        if not same_market:
            raise ValueError("a series holds one provider, instrument and timeframe")
        opens = [c.open_time for c in candles]
        if any(later <= earlier for earlier, later in pairwise(opens)):
            raise ValueError("candles must be strictly ascending")

        def floats(name: str) -> FloatArray:
            return np.array([float(getattr(c, name)) for c in candles], dtype=np.float64)

        taker = [c.taker_buy_base_volume for c in candles]
        return cls(
            timeframe=first.timeframe,
            open_time=tuple(opens),
            close_time=tuple(c.close_time for c in candles),
            open=floats("open"),
            high=floats("high"),
            low=floats("low"),
            close=floats("close"),
            volume=floats("volume"),
            taker_buy_volume=np.array(
                [np.nan if value is None else float(value) for value in taker], dtype=np.float64
            ),
            is_continuous=all(
                first.timeframe.next_open(earlier) == later for earlier, later in pairwise(opens)
            ),
        )

    def upto(self, end: int) -> CandleSeries:
        """The first `end` candles. Used to prove results never depend on later data."""
        return CandleSeries(
            timeframe=self.timeframe,
            open_time=self.open_time[:end],
            close_time=self.close_time[:end],
            open=self.open[:end],
            high=self.high[:end],
            low=self.low[:end],
            close=self.close[:end],
            volume=self.volume[:end],
            taker_buy_volume=self.taker_buy_volume[:end],
            is_continuous=self.is_continuous,
        )
