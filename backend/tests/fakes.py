"""An in-memory provider for service tests. Everything it returns is test data."""

from collections.abc import AsyncIterator, Iterable, Sequence
from datetime import datetime, timedelta
from decimal import Decimal

from trading_intel.core.clock import to_epoch_ms
from trading_intel.data_providers.base import (
    CandleSubscription,
    MarketEvent,
    ProviderCapabilities,
)
from trading_intel.domain.base import DataOrigin
from trading_intel.domain.candles import ClosedCandle, Timeframe
from trading_intel.domain.instruments import Instrument, InstrumentRules


def make_candle(
    provider_id: int,
    instrument_id: int,
    timeframe: Timeframe,
    open_time: datetime,
    *,
    origin: DataOrigin = DataOrigin.BACKFILL,
    close: Decimal = Decimal(105),
    volume: Decimal = Decimal(5),
) -> ClosedCandle:
    return ClosedCandle(
        provider_id=provider_id,
        instrument_id=instrument_id,
        timeframe=timeframe,
        open_time=open_time,
        close_time=timeframe.close_time(open_time),
        open=Decimal(100),
        high=Decimal(110),
        low=Decimal(90),
        close=close,
        volume=volume,
        quote_volume=Decimal(500),
        trade_count=3,
        provider_open_time_raw=to_epoch_ms(open_time),
        data_origin=origin,
        received_at=open_time + timedelta(minutes=1),
    )


class FakeProvider:
    """Serves whatever candles it holds. `holes` are open times it never returns."""

    def __init__(self, provider_id: int, holes: Iterable[datetime] = ()) -> None:
        self.provider_id = provider_id
        self.holes = set(holes)
        self.overrides: dict[datetime, ClosedCandle] = {}
        self.rules: InstrumentRules | None = None
        self.fail_after: int | None = None
        self.served = 0
        self.history_calls = 0
        self.events: list[MarketEvent] = []

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(bid_ask=True)

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def get_server_time(self) -> datetime:
        raise NotImplementedError

    async def get_instrument_rules(self, instrument: Instrument) -> InstrumentRules:
        assert self.rules is not None
        return self.rules

    async def get_historical_candles(
        self,
        instrument: Instrument,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
        origin: DataOrigin = DataOrigin.BACKFILL,
    ) -> AsyncIterator[ClosedCandle]:
        self.history_calls += 1
        cursor = start
        while cursor < end:
            if cursor not in self.holes:
                if self.fail_after is not None and self.served >= self.fail_after:
                    raise ConnectionError("forced stop")
                self.served += 1
                yield self.overrides.get(cursor) or make_candle(
                    self.provider_id, instrument.id, timeframe, cursor, origin=origin
                )
            cursor = timeframe.next_open(cursor)

    async def stream_market(
        self,
        subscriptions: Sequence[CandleSubscription],
        book_instruments: Sequence[Instrument],
        *,
        mark_instruments: Sequence[Instrument] = (),
        liquidation_instruments: Sequence[Instrument] = (),
    ) -> AsyncIterator[MarketEvent]:
        for event in self.events:
            yield event
