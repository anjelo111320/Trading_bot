"""Provider protocols. Optional capabilities are separate, since no provider has everything."""

from collections.abc import AsyncIterator, Sequence
from datetime import datetime
from typing import Protocol

from trading_intel.domain.base import DomainModel
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


class MarketDataProvider(Protocol):
    @property
    def capabilities(self) -> ProviderCapabilities: ...

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def get_server_time(self) -> datetime: ...

    async def get_instrument_rules(self, instrument: Instrument) -> InstrumentRules: ...

    def get_historical_candles(
        self, instrument: Instrument, timeframe: Timeframe, start: datetime, end: datetime
    ) -> AsyncIterator[ClosedCandle]: ...

    def stream_candles(
        self, subscriptions: Sequence[CandleSubscription]
    ) -> AsyncIterator[CandleEvent]: ...


class TopOfBookCapable(Protocol):
    def stream_top_of_book(self, instruments: Sequence[Instrument]) -> AsyncIterator[TopOfBook]: ...


class DerivativesCapable(Protocol):
    def get_funding_history(
        self, instrument: Instrument, start: datetime
    ) -> AsyncIterator[FundingRate]: ...

    def stream_mark_price(self, instruments: Sequence[Instrument]) -> AsyncIterator[MarkPrice]: ...

    async def get_open_interest(self, instrument: Instrument) -> OpenInterest: ...

    def stream_liquidations(
        self, instruments: Sequence[Instrument]
    ) -> AsyncIterator[LiquidationSample]: ...
