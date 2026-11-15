"""The worker's live quote reader (D071), against a fake bus. Nothing reaches Redis."""

from datetime import UTC, datetime
from decimal import Decimal as D
from uuid import uuid7

from trading_intel.domain.base import DataOrigin
from trading_intel.domain.events import (
    MARKET_PRICE,
    SCHEMA_VERSION,
    EventEnvelope,
    MarketPricePayload,
)
from trading_intel.entrypoints.quant_worker import RedisQuotes
from trading_intel.market_data.ingest import topic_price


class Bus:
    def __init__(self, envelope: EventEnvelope | None) -> None:
        self.envelope = envelope
        self.asked: list[str] = []

    async def latest(self, topic: str) -> EventEnvelope | None:
        self.asked.append(topic)
        return self.envelope


async def test_a_live_quote_is_read_from_what_the_ingestor_published() -> None:
    at = datetime(2026, 11, 15, 0, 0, 33, tzinfo=UTC)
    payload = MarketPricePayload(
        provider="binance_usdm", instrument_id=7, bid="91200.1", ask="91200.2", received_at=at
    )
    envelope = EventEnvelope(
        event_id=uuid7(), event_type=MARKET_PRICE, schema_version=SCHEMA_VERSION,
        occurred_at=at, seq=1, data_origin=DataOrigin.LIVE,
        payload=payload.model_dump(mode="json"),
    )  # fmt: skip
    bus = Bus(envelope)
    quotes = RedisQuotes(bus, "binance_usdm")  # type: ignore[arg-type]
    assert await quotes.quote(7) == (at, D("91200.1"), D("91200.2"))
    assert bus.asked == [topic_price("binance_usdm", 7)]
    assert await RedisQuotes(Bus(None), "binance_usdm").quote(7) is None  # type: ignore[arg-type]
