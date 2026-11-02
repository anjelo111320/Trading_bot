from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from redis.asyncio import Redis

from tests.conftest import make_settings
from trading_intel.core.clock import FixedClock
from trading_intel.domain.base import DataOrigin
from trading_intel.domain.events import MARKET_CANDLE, MARKET_PRICE, MarketPricePayload
from trading_intel.events.redis_transport import (
    CLOSED_CANDLE_STREAM,
    ClosedCandleConsumer,
    RedisEventBus,
)

pytestmark = pytest.mark.integration

NOW = datetime(2026, 1, 1, tzinfo=UTC)
PAYLOAD = MarketPricePayload(provider="p", instrument_id=1, bid="1", ask="2", received_at=NOW)


@pytest.fixture
async def redis() -> AsyncIterator[Redis]:
    client: Redis = Redis.from_url(make_settings().redis_url.get_secret_value())
    await client.flushdb()
    yield client
    await client.aclose()


def bus(client: Redis) -> RedisEventBus:
    return RedisEventBus(client, FixedClock(NOW))


async def test_durable_event_reaches_a_consumer_group(redis: Redis) -> None:
    events = bus(redis)
    assert await events.publish_durable("t", MARKET_CANDLE, DataOrigin.LIVE, PAYLOAD)
    consumer = ClosedCandleConsumer(redis, "workers", "one")
    await consumer.ensure_group()
    received = []

    async def handler(envelope: object) -> None:
        received.append(envelope)

    assert await consumer.process_once(handler) == 1
    assert received[0].event_type == MARKET_CANDLE
    assert received[0].data_origin is DataOrigin.LIVE
    assert await consumer.process_once(handler) == 0


async def test_unacknowledged_event_is_redelivered_after_a_consumer_restart(redis: Redis) -> None:
    events = bus(redis)
    await events.publish_durable("t", MARKET_CANDLE, DataOrigin.LIVE, PAYLOAD)
    consumer = ClosedCandleConsumer(redis, "workers", "one")
    await consumer.ensure_group()

    async def crash(_: object) -> None:
        raise RuntimeError("consumer died")

    with pytest.raises(RuntimeError):
        await consumer.process_once(crash)

    received = []

    async def handler(envelope: object) -> None:
        received.append(envelope)

    restarted = ClosedCandleConsumer(redis, "workers", "one")
    await restarted.ensure_group()
    assert await restarted.process_once(handler) == 1
    assert len(received) == 1


async def test_creating_the_group_twice_is_harmless(redis: Redis) -> None:
    consumer = ClosedCandleConsumer(redis, "workers", "one")
    await consumer.ensure_group()
    await consumer.ensure_group()


async def test_publishing_twice_is_visible_as_two_events_with_rising_seq(redis: Redis) -> None:
    events = bus(redis)
    await events.publish_latest("t", MARKET_PRICE, DataOrigin.LIVE, PAYLOAD)
    first = await events.latest("t")
    await events.publish_latest("t", MARKET_PRICE, DataOrigin.LIVE, PAYLOAD)
    second = await events.latest("t")
    assert first is not None and second is not None
    assert second.seq == first.seq + 1
    assert second.event_id != first.event_id


async def test_latest_value_expires_so_old_prices_cannot_look_current(redis: Redis) -> None:
    await bus(redis).publish_latest("t", MARKET_PRICE, DataOrigin.LIVE, PAYLOAD)
    assert 0 < await redis.ttl("latest:t") <= 60


async def test_a_redis_failure_is_reported_rather_than_raised() -> None:
    dead: Redis = Redis.from_url("redis://127.0.0.1:1/0")
    events = bus(dead)
    assert not await events.publish_durable("t", MARKET_CANDLE, DataOrigin.LIVE, PAYLOAD)
    assert not await events.publish_latest("t", MARKET_PRICE, DataOrigin.LIVE, PAYLOAD)
    assert not await events.is_available()
    assert events.failures == 2
    await dead.aclose()


async def test_stream_length_is_bounded(redis: Redis) -> None:
    await bus(redis).publish_durable("t", MARKET_CANDLE, DataOrigin.LIVE, PAYLOAD)
    assert await redis.xlen(CLOSED_CANDLE_STREAM) == 1
