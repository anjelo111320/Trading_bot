"""The envelope carried by every event, and the payloads of each event type."""

from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from trading_intel.core.clock import UtcDatetime
from trading_intel.domain.base import DataOrigin, DomainModel
from trading_intel.domain.candles import ClosedCandle, FormingCandle, Timeframe

MARKET_PRICE = "market.price"
MARKET_CANDLE = "market.candle"
MARKET_STATUS = "market.status"
SCHEMA_VERSION = 1


class EventEnvelope(DomainModel):
    event_id: UUID
    event_type: str
    schema_version: int
    occurred_at: UtcDatetime
    seq: int
    data_origin: DataOrigin
    payload: dict[str, Any]


class _Payload(BaseModel):
    """Payloads are wire formats, so money is a string."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class MarketPricePayload(_Payload):
    provider: str
    instrument_id: int
    bid: str
    ask: str
    received_at: UtcDatetime


class MarketCandlePayload(_Payload):
    provider: str
    instrument_id: int
    timeframe: Timeframe
    is_closed: bool
    open_time: UtcDatetime
    close_time: UtcDatetime
    open: str
    high: str
    low: str
    close: str
    volume: str


class MarketStatusPayload(_Payload):
    provider: str
    state: Literal["HEALTHY", "DEGRADED", "STALE", "DISCONNECTED", "RECOVERING"]
    reasons: list[str]
    last_event_at: UtcDatetime | None = None
    lag_seconds: float | None = None
    open_gaps: int = 0
    clock_skew_ms: float | None = None


def plain(value: Decimal) -> str:
    """A Decimal in plain notation, so 0E-8 never reaches a client."""
    return format(value, "f")


def candle_payload(provider: str, candle: ClosedCandle | FormingCandle) -> MarketCandlePayload:
    return MarketCandlePayload(
        provider=provider,
        instrument_id=candle.instrument_id,
        timeframe=candle.timeframe,
        is_closed=isinstance(candle, ClosedCandle),
        open_time=candle.open_time,
        close_time=candle.close_time,
        open=plain(candle.open),
        high=plain(candle.high),
        low=plain(candle.low),
        close=plain(candle.close),
        volume=plain(candle.volume),
    )


def event_json_schemas() -> dict[str, dict[str, Any]]:
    return {
        "envelope": EventEnvelope.model_json_schema(),
        MARKET_PRICE: MarketPricePayload.model_json_schema(),
        MARKET_CANDLE: MarketCandlePayload.model_json_schema(),
        MARKET_STATUS: MarketStatusPayload.model_json_schema(),
    }
