"""Provider protocols. Optional capabilities are separate, since no provider has everything."""

from collections.abc import AsyncIterator, Sequence
from datetime import datetime
from typing import Protocol

from trading_intel.core.clock import UtcDatetime
from trading_intel.domain.base import DataOrigin, DomainModel
from trading_intel.domain.candles import CandleEvent, ClosedCandle, Timeframe
from trading_intel.domain.instruments import Instrument, InstrumentRules
from trading_intel.domain.market import (
    FundingRate,
    LiquidationSample,
    MarkPrice,
    OpenInterest,
    TopOfBook,
)


class ProviderCapabilities(DomainModel):
    candles: bool = True
    bid_ask: bool = False
    depth: bool = False
    funding: bool = False
    open_interest: bool = False
    liquidations: bool = False


class CandleSubscription(DomainModel):
    instrument: Instrument
    timeframe: Timeframe


class LinkUp(DomainModel):
    """A stream connection opened."""

    route: str
    at: UtcDatetime


class LinkDown(DomainModel):
    """A stream connection ended. Reconnection is already under way."""

    route: str
    reason: str
    at: UtcDatetime


class MarketEventRejected(DomainModel):
    """A frame was refused. It is counted, and the connection stays up."""

    route: str
    reason: str
    at: UtcDatetime


MarketEvent = (
    CandleEvent
    | TopOfBook
    | MarkPrice
    | LiquidationSample
    | LinkUp
    | LinkDown
    | MarketEventRejected
)


class MarketDataProvider(Protocol):
    @property
    def capabilities(self) -> ProviderCapabilities: ...

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def get_server_time(self) -> datetime: ...

    async def get_instrument_rules(self, instrument: Instrument) -> InstrumentRules: ...

    def get_historical_candles(
        self,
        instrument: Instrument,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
        origin: DataOrigin = DataOrigin.BACKFILL,
    ) -> AsyncIterator[ClosedCandle]: ...

    def stream_market(
        self,
        subscriptions: Sequence[CandleSubscription],
        book_instruments: Sequence[Instrument],
        *,
        mark_instruments: Sequence[Instrument] = (),
        liquidation_instruments: Sequence[Instrument] = (),
    ) -> AsyncIterator[MarketEvent]: ...


class DerivativesCapable(Protocol):
    def get_funding_history(
        self, instrument: Instrument, start: datetime
    ) -> AsyncIterator[FundingRate]: ...

    async def get_open_interest(self, instrument: Instrument) -> OpenInterest: ...

    def get_open_interest_history(
        self, instrument: Instrument, start: datetime
    ) -> AsyncIterator[OpenInterest]: ...
