"""A deterministic provider for development without a network.

The same seed always gives the same candles. All output has data_origin=synthetic.
"""

import asyncio
import hashlib
import math
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from datetime import UTC, datetime
from decimal import Decimal

from trading_intel.core.clock import Clock, to_epoch_ms
from trading_intel.data_providers.base import (
    CandleSubscription,
    LinkUp,
    MarketEvent,
    ProviderCapabilities,
)
from trading_intel.domain.base import DataOrigin
from trading_intel.domain.candles import ClosedCandle, FormingCandle, Timeframe
from trading_intel.domain.instruments import Instrument, InstrumentRules
from trading_intel.domain.market import TopOfBook

ROUTE = "synthetic"
_EPOCH = datetime(2020, 1, 1, tzinfo=UTC)
_CENT = Decimal("0.01")


def _noise(seed: int, instrument_id: int, moment: int) -> float:
    """A repeatable value in [0, 1), free of any process-level random state."""
    digest = hashlib.sha256(f"{seed}:{instrument_id}:{moment}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def price_at(seed: int, instrument_id: int, at: datetime) -> Decimal:
    """A wandering price, as a pure function of time."""
    minutes = (at - _EPOCH).total_seconds() / 60
    base = 1000.0 * instrument_id
    trend = 0.05 * math.sin(minutes / 2880) + 0.02 * math.sin(minutes / 233)
    ripple = 0.002 * (_noise(seed, instrument_id, int(minutes)) - 0.5)
    return Decimal(str(round(base * (1 + trend + ripple), 2)))


class SyntheticProvider:
    def __init__(
        self,
        provider_id: int,
        clock: Clock,
        *,
        seed: int = 7,
        tick_seconds: float = 1.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._provider_id = provider_id
        self._clock = clock
        self._seed = seed
        self._tick_seconds = tick_seconds
        self._sleep = sleep

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(bid_ask=True)

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def get_server_time(self) -> datetime:
        return self._clock.now()

    async def get_instrument_rules(self, instrument: Instrument) -> InstrumentRules:
        return InstrumentRules(
            status="SYNTHETIC",
            tick_size=_CENT,
            lot_step=Decimal("0.001"),
            min_qty=Decimal("0.001"),
            max_qty=Decimal(1000),
            min_notional=Decimal(5),
            raw={"origin": "synthetic"},
        )

    def _candle_fields(
        self, instrument: Instrument, timeframe: Timeframe, open_time: datetime, until: datetime
    ) -> dict[str, object]:
        step = timeframe.delta / 12
        points = [
            price_at(self._seed, instrument.id, open_time + step * i)
            for i in range(13)
            if open_time + step * i <= until
        ] or [price_at(self._seed, instrument.id, open_time)]
        volume = Decimal(str(round(5 + 10 * _noise(self._seed, instrument.id, 1), 3)))
        close = points[-1]
        return {
            "provider_id": self._provider_id,
            "instrument_id": instrument.id,
            "timeframe": timeframe,
            "open_time": open_time,
            "close_time": timeframe.close_time(open_time),
            "open": points[0],
            "high": max(points),
            "low": min(points),
            "close": close,
            "volume": volume,
            "quote_volume": (volume * close).quantize(_CENT),
            "trade_count": 10,
            "provider_open_time_raw": to_epoch_ms(open_time),
            "data_origin": DataOrigin.SYNTHETIC,
            "received_at": self._clock.now(),
        }

    def _closed(
        self, instrument: Instrument, timeframe: Timeframe, open_time: datetime
    ) -> ClosedCandle:
        until = timeframe.next_open(open_time)
        return ClosedCandle.model_validate(
            self._candle_fields(instrument, timeframe, open_time, until)
        )

    async def get_historical_candles(
        self,
        instrument: Instrument,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
        origin: DataOrigin = DataOrigin.SYNTHETIC,
    ) -> AsyncIterator[ClosedCandle]:
        """Origin is ignored on purpose: this data is synthetic whatever the caller asks."""
        last_closed = timeframe.floor(self._clock.now())
        cursor = start
        while cursor < end and cursor < last_closed:
            yield self._closed(instrument, timeframe, cursor)
            cursor = timeframe.next_open(cursor)

    def _book(self, instrument: Instrument) -> TopOfBook:
        now = self._clock.now()
        mid = price_at(self._seed, instrument.id, now)
        return TopOfBook(
            provider_id=self._provider_id,
            instrument_id=instrument.id,
            bid_price=mid - _CENT,
            bid_quantity=Decimal(1),
            ask_price=mid + _CENT,
            ask_quantity=Decimal(1),
            received_at=now,
        )

    async def stream_market(
        self,
        subscriptions: Sequence[CandleSubscription],
        book_instruments: Sequence[Instrument],
        *,
        mark_instruments: Sequence[Instrument] = (),
        liquidation_instruments: Sequence[Instrument] = (),
    ) -> AsyncIterator[MarketEvent]:
        yield LinkUp(route=ROUTE, at=self._clock.now())
        current = {s: s.timeframe.floor(self._clock.now()) for s in subscriptions}
        while True:
            now = self._clock.now()
            for subscription in subscriptions:
                instrument, timeframe = subscription.instrument, subscription.timeframe
                opened = timeframe.floor(now)
                if opened > current[subscription]:
                    yield self._closed(instrument, timeframe, current[subscription])
                    current[subscription] = opened
                yield FormingCandle.model_validate(
                    self._candle_fields(instrument, timeframe, opened, now)
                )
            for instrument in book_instruments:
                yield self._book(instrument)
            await self._sleep(self._tick_seconds)
