"""Signal score, trial 1. Pre-registered in docs/34-SIGNAL-SCORE.md.

Four facts known when a signal's setup candle closed, each for the trade, against it or
unknown. A signal is weak when two or more are against it. This is an idea to test, and
never a chance of winning.
"""

import statistics
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final

from trading_intel.domain.signals import Side
from trading_intel.technical_analysis.series import CandleSeries
from trading_intel.technical_analysis.smoothing import sma
from trading_intel.technical_analysis.volume import relative_volume

SCORE_VERSION: Final = 1
TREND_DAYS: Final = 200
VOLUME_CANDLES: Final = 20
FUNDING_RECENT: Final = timedelta(hours=24)
FUNDING_HISTORY: Final = timedelta(days=90)
WEAK_AGAINST: Final = 2

Reading = bool | None
"""For the trade, against it, or unknown."""


@dataclass(frozen=True)
class Conditions:
    long_term_trend: Reading
    bitcoin_trend: Reading
    volume: Reading
    funding: Reading
    bitcoin_applies: bool = True

    def readings(self) -> tuple[Reading, ...]:
        if self.bitcoin_applies:
            return self.long_term_trend, self.bitcoin_trend, self.volume, self.funding
        return self.long_term_trend, self.volume, self.funding

    @property
    def known(self) -> bool:
        return None not in self.readings()

    @property
    def against(self) -> int:
        return sum(1 for reading in self.readings() if reading is False)

    @property
    def weak(self) -> bool | None:
        """Undefined while a condition is unknown, so such a signal is never scored."""
        return self.against >= WEAK_AGAINST if self.known else None

    def as_record(self) -> dict[str, Any]:
        """Stored with a live signal as information only, since the score failed (D046)."""
        return {
            "version": SCORE_VERSION,
            "weak": self.weak,
            "against": self.against,
            "long_term_trend": self.long_term_trend,
            "bitcoin_trend": self.bitcoin_trend,
            "bitcoin_applies": self.bitcoin_applies,
            "volume": self.volume,
            "funding": self.funding,
        }


class LongTermTrend:
    """The last daily close against the mean of the last 200, as known at a moment."""

    def __init__(self, days: CandleSeries, period: int = TREND_DAYS) -> None:
        self._close_times = days.close_time
        self._close = days.close
        self._mean = sma(days.close, period)

    def agrees(self, moment: datetime, side: Side) -> Reading:
        position = bisect_right(self._close_times, moment) - 1
        if position < 0:
            return None
        mean = float(self._mean[position])
        if mean != mean:
            return None
        close = float(self._close[position])
        return close > mean if side is Side.LONG else close < mean


class VolumeView:
    """The setup candle's volume against the mean of the 20 candles before it."""

    def __init__(self, setup: CandleSeries, period: int = VOLUME_CANDLES) -> None:
        self._index = {moment: i for i, moment in enumerate(setup.close_time)}
        self._ratio = relative_volume(setup.volume, period)

    def confirms(self, moment: datetime) -> Reading:
        index = self._index.get(moment)
        if index is None:
            return None
        ratio = float(self._ratio[index])
        return None if ratio != ratio else ratio >= 1.0


class FundingView:
    """The last day's mean funding rate against the coin's own 90-day median.

    Only rates paid by the moment count. Decimals keep a rate equal to its median equal.
    """

    def __init__(self, rates: Sequence[tuple[datetime, Decimal]]) -> None:
        self._times = [at for at, _ in rates]
        self._rates = [rate for _, rate in rates]

    def agrees(self, moment: datetime, side: Side) -> Reading:
        if not self._times or self._times[0] > moment - FUNDING_HISTORY:
            return None
        end = bisect_right(self._times, moment)
        recent = self._rates[bisect_right(self._times, moment - FUNDING_RECENT) : end]
        if not recent:
            return None
        history = self._rates[bisect_right(self._times, moment - FUNDING_HISTORY) : end]
        level = sum(recent, Decimal(0)) / len(recent)
        usual = statistics.median(history)
        return level <= usual if side is Side.LONG else level >= usual


@dataclass(frozen=True)
class ScoreViews:
    """One coin's views for one strategy. `bitcoin` is None for Bitcoin's own trades."""

    trend: LongTermTrend
    bitcoin: LongTermTrend | None
    volume: VolumeView
    funding: FundingView

    def conditions(self, moment: datetime, side: Side) -> Conditions:
        return Conditions(
            long_term_trend=self.trend.agrees(moment, side),
            bitcoin_trend=None if self.bitcoin is None else self.bitcoin.agrees(moment, side),
            volume=self.volume.confirms(moment),
            funding=self.funding.agrees(moment, side),
            bitcoin_applies=self.bitcoin is not None,
        )
