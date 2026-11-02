"""Candles. Closed and forming are separate types, so one cannot pass for the other."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import model_validator

from trading_intel.core.clock import UtcDatetime, ensure_utc, to_epoch_ms
from trading_intel.domain.base import DataOrigin, DomainModel

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

# Before any provider's history, and far in the future. A microsecond value read as
# milliseconds falls outside this range, which is the point of the check.
EARLIEST_PLAUSIBLE_MS = 1_230_768_000_000  # 2009-01-01
LATEST_PLAUSIBLE_MS = 4_102_444_800_000  # 2100-01-01

_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}


class Timeframe(StrEnum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"

    @property
    def seconds(self) -> int:
        return _SECONDS[self.value]

    @property
    def delta(self) -> timedelta:
        return timedelta(seconds=self.seconds)

    def is_aligned(self, at: datetime) -> bool:
        return to_epoch_ms(at) % (self.seconds * 1000) == 0

    def floor(self, at: datetime) -> datetime:
        """The open time of the candle that contains this moment."""
        elapsed = ensure_utc(at) - _EPOCH
        return _EPOCH + (elapsed // self.delta) * self.delta

    def close_time(self, open_time: datetime) -> datetime:
        """Providers end a candle 1 ms before the next one opens."""
        return open_time + self.delta - timedelta(milliseconds=1)

    def next_open(self, open_time: datetime) -> datetime:
        return open_time + self.delta


def candle_violations(
    timeframe: Timeframe,
    open_time: datetime,
    close_time: datetime,
    open_: Decimal,
    high: Decimal,
    low: Decimal,
    close: Decimal,
    volume: Decimal,
    quote_volume: Decimal,
) -> tuple[str, ...]:
    """Return the reason codes for an invalid candle. Empty means valid."""
    problems: list[str] = []
    if min(open_, high, low, close) <= 0:
        problems.append("non_positive_price")
    if high < max(open_, close, low):
        problems.append("high_below_body")
    if low > min(open_, close, high):
        problems.append("low_above_body")
    if volume < 0 or quote_volume < 0:
        problems.append("negative_volume")
    if not timeframe.is_aligned(open_time):
        problems.append("open_time_misaligned")
    if close_time != timeframe.close_time(open_time):
        problems.append("close_time_mismatch")
    if not EARLIEST_PLAUSIBLE_MS <= to_epoch_ms(open_time) <= LATEST_PLAUSIBLE_MS:
        problems.append("implausible_timestamp")
    return tuple(problems)


class _Candle(DomainModel):
    provider_id: int
    instrument_id: int
    timeframe: Timeframe
    open_time: UtcDatetime
    close_time: UtcDatetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    quote_volume: Decimal
    taker_buy_base_volume: Decimal | None = None
    taker_buy_quote_volume: Decimal | None = None
    trade_count: int
    first_trade_id: int | None = None
    last_trade_id: int | None = None
    provider_open_time_raw: int
    data_origin: DataOrigin
    received_at: UtcDatetime

    @model_validator(mode="after")
    def _check_invariants(self) -> Self:
        problems = candle_violations(
            self.timeframe,
            self.open_time,
            self.close_time,
            self.open,
            self.high,
            self.low,
            self.close,
            self.volume,
            self.quote_volume,
        )
        if self.trade_count < 0:
            problems = (*problems, "negative_trade_count")
        if problems:
            raise ValueError(f"invalid candle: {', '.join(problems)}")
        return self


class ClosedCandle(_Candle):
    """A finished candle. The only kind that may be stored or analysed."""


class FormingCandle(_Candle):
    """An unfinished candle. Its values will change, so it is display data only."""


CandleEvent = ClosedCandle | FormingCandle
