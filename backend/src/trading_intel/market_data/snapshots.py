"""One row per instrument per minute. Raw top-of-book frames are never stored.

Spread cannot be fetched later, so a minute with no data stays missing and is never filled.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from trading_intel.database.repositories.operations import SnapshotRow
from trading_intel.domain.base import DataOrigin
from trading_intel.domain.candles import Timeframe
from trading_intel.domain.market import MarkPrice, OpenInterest, TopOfBook


@dataclass
class _Minute:
    best_bid: Decimal | None = None
    best_ask: Decimal | None = None
    spread_min: Decimal | None = None
    spread_max: Decimal | None = None
    spread_last: Decimal | None = None
    spread_sum: Decimal = field(default_factory=Decimal)
    samples: int = 0
    crossed: int = 0
    mark_price: Decimal | None = None
    index_price: Decimal | None = None
    open_interest: Decimal | None = None


class MinuteAggregator:
    def __init__(self, provider_id: int, origin: DataOrigin = DataOrigin.LIVE) -> None:
        self._provider_id = provider_id
        self._origin = origin
        self._minutes: dict[tuple[int, datetime], _Minute] = {}

    def _bucket(self, instrument_id: int, at: datetime) -> _Minute:
        return self._minutes.setdefault((instrument_id, Timeframe.M1.floor(at)), _Minute())

    def add_book(self, book: TopOfBook) -> None:
        minute = self._bucket(book.instrument_id, book.received_at)
        minute.best_bid = book.bid_price
        minute.best_ask = book.ask_price
        if book.is_crossed:
            minute.crossed += 1  # A crossed book is flagged, and kept out of the statistics.
            return
        spread = book.spread
        minute.samples += 1
        minute.spread_sum += spread
        minute.spread_last = spread
        minute.spread_min = spread if minute.spread_min is None else min(minute.spread_min, spread)
        minute.spread_max = spread if minute.spread_max is None else max(minute.spread_max, spread)

    def add_mark(self, mark: MarkPrice) -> None:
        minute = self._bucket(mark.instrument_id, mark.received_at)
        minute.mark_price = mark.mark_price
        minute.index_price = mark.index_price

    def add_open_interest(self, interest: OpenInterest) -> None:
        minute = self._bucket(interest.instrument_id, interest.received_at)
        minute.open_interest = interest.open_interest

    def flush(self, now: datetime) -> list[SnapshotRow]:
        """Return every minute that has finished."""
        current = Timeframe.M1.floor(now)
        finished = sorted(key for key in self._minutes if key[1] < current)
        return [self._row(key, self._minutes.pop(key), now) for key in finished]

    def _row(self, key: tuple[int, datetime], minute: _Minute, now: datetime) -> SnapshotRow:
        instrument_id, minute_start = key
        mean = minute.spread_sum / minute.samples if minute.samples else None
        return SnapshotRow(
            provider_id=self._provider_id,
            instrument_id=instrument_id,
            minute_start=minute_start,
            best_bid=minute.best_bid,
            best_ask=minute.best_ask,
            spread_min=minute.spread_min,
            spread_mean=mean,
            spread_max=minute.spread_max,
            spread_last=minute.spread_last,
            sample_count=minute.samples,
            crossed_book_count=minute.crossed,
            mark_price=minute.mark_price,
            index_price=minute.index_price,
            open_interest=minute.open_interest,
            data_origin=self._origin,
            received_at=now,
        )
