"""Market data other than candles."""

from decimal import Decimal
from typing import Literal

from trading_intel.core.clock import UtcDatetime
from trading_intel.domain.base import DataOrigin, DomainModel


class TopOfBook(DomainModel):
    provider_id: int
    instrument_id: int
    bid_price: Decimal
    bid_quantity: Decimal
    ask_price: Decimal
    ask_quantity: Decimal
    received_at: UtcDatetime

    @property
    def spread(self) -> Decimal:
        return self.ask_price - self.bid_price

    @property
    def is_crossed(self) -> bool:
        """Crossed or locked. A real book has ask above bid."""
        return self.ask_price <= self.bid_price


class FundingRate(DomainModel):
    provider_id: int
    instrument_id: int
    funding_time: UtcDatetime
    funding_rate: Decimal
    mark_price: Decimal | None = None
    data_origin: DataOrigin
    received_at: UtcDatetime


class MarkPrice(DomainModel):
    provider_id: int
    instrument_id: int
    mark_price: Decimal
    index_price: Decimal
    last_funding_rate: Decimal | None = None
    next_funding_time: UtcDatetime | None = None
    event_time: UtcDatetime
    received_at: UtcDatetime


class OpenInterest(DomainModel):
    provider_id: int
    instrument_id: int
    open_interest: Decimal
    event_time: UtcDatetime
    received_at: UtcDatetime


class LiquidationSample(DomainModel):
    """One sampled order. The stream is limited, so this is never a complete record."""

    provider_id: int
    instrument_id: int
    event_time: UtcDatetime
    side: Literal["BUY", "SELL"]
    price: Decimal
    quantity: Decimal
    received_at: UtcDatetime
