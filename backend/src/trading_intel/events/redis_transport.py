"""Redis Streams for closed candles, Pub/Sub for values where only the latest matters.

A Redis failure never stops the ingest path: publishing reports failure instead of raising,
and missed closed-candle events are replayed from PostgreSQL.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, Final
from uuid import uuid7

import structlog
from pydantic import BaseModel
from redis.asyncio import Redis
from redis.exceptions import RedisError, ResponseError

from trading_intel.core.clock import Clock
from trading_intel.domain.base import DataOrigin
from trading_intel.domain.events import SCHEMA_VERSION, EventEnvelope

log = structlog.get_logger(__name__)

CLOSED_CANDLE_STREAM: Final = "events:market.candle.closed"
LIVE_CHANNEL_PREFIX: Final = "live:"
LATEST_PREFIX: Final = "latest:"
STREAM_MAX_LENGTH: Final = 50_000
LATEST_TTL_SECONDS: Final = 60
BLOCK_MILLISECONDS: Final = 1000

Handler = Callable[[EventEnvelope], Awaitable[None]]


class RedisEventBus:
    def __init__(self, redis: Redis, clock: Clock) -> None:
        self._redis = redis
        self._clock = clock
        self.failures = 0

    async def _envelope(
        self,
        topic: str,
        event_type: str,
        origin: DataOrigin,
        payload: BaseModel,
    ) -> EventEnvelope:
        return EventEnvelope(
            event_id=uuid7(),
            event_type=event_type,
            schema_version=SCHEMA_VERSION,
            occurred_at=self._clock.now(),
            seq=await self._redis.incr(f"seq:{topic}"),
            data_origin=origin,
            payload=payload.model_dump(mode="json"),
        )

    async def publish_durable(
        self, topic: str, event_type: str, origin: DataOrigin, payload: BaseModel
    ) -> bool:
        """Add to the closed-candle stream and tell live clients. False if Redis failed."""
        try:
            envelope = await self._envelope(topic, event_type, origin, payload)
            body = envelope.model_dump_json()
            await self._redis.xadd(
                CLOSED_CANDLE_STREAM,
                {"topic": topic, "event": body},
                maxlen=STREAM_MAX_LENGTH,
                approximate=True,
            )
            await self._redis.publish(f"{LIVE_CHANNEL_PREFIX}{topic}", body)
        except (RedisError, OSError) as error:
            self._note_failure(error)
            return False
        return True

    async def publish_latest(
        self, topic: str, event_type: str, origin: DataOrigin, payload: BaseModel
    ) -> bool:
        """Replace the latest value and tell live clients. False if Redis failed."""
        try:
            envelope = await self._envelope(topic, event_type, origin, payload)
            body = envelope.model_dump_json()
            await self._redis.set(f"{LATEST_PREFIX}{topic}", body, ex=LATEST_TTL_SECONDS)
            await self._redis.publish(f"{LIVE_CHANNEL_PREFIX}{topic}", body)
        except (RedisError, OSError) as error:
            self._note_failure(error)
            return False
        return True

    async def latest(self, topic: str) -> EventEnvelope | None:
        body = await self._redis.get(f"{LATEST_PREFIX}{topic}")
        return EventEnvelope.model_validate_json(body) if body else None

    async def is_available(self) -> bool:
        try:
            await self._redis.ping()
        except RedisError, OSError:
            return False
        return True

    def _note_failure(self, error: Exception) -> None:
        self.failures += 1
        log.warning("event_publish_failed", error=type(error).__name__)

    async def live_events(self, pattern: str = "*") -> AsyncIterator[tuple[str, str]]:
        """Yield (topic, body) for live events. Used by the WebSocket gateway."""
        pubsub = self._redis.pubsub()
        await pubsub.psubscribe(f"{LIVE_CHANNEL_PREFIX}{pattern}")
        try:
            async for message in pubsub.listen():
                if message["type"] != "pmessage":
                    continue
                channel = message["channel"]
                topic = channel.decode() if isinstance(channel, bytes) else channel
                data = message["data"]
                body = data.decode() if isinstance(data, bytes) else data
                yield topic.removeprefix(LIVE_CHANNEL_PREFIX), body
        finally:
            await pubsub.aclose()  # type: ignore[no-untyped-call]


class ClosedCandleConsumer:
    """At-least-once delivery, so handlers must be idempotent."""

    def __init__(self, redis: Redis, group: str, consumer: str) -> None:
        self._redis = redis
        self._group = group
        self._consumer = consumer

    async def ensure_group(self) -> None:
        try:
            await self._redis.xgroup_create(
                CLOSED_CANDLE_STREAM, self._group, id="0", mkstream=True
            )
        except ResponseError as error:
            if "BUSYGROUP" not in str(error):
                raise

    async def process_once(self, handler: Handler, *, count: int = 100) -> int:
        """Handle unacknowledged events first, then new ones. Returns how many were handled."""
        handled = await self._drain("0", handler, count)
        return handled + await self._drain(">", handler, count)

    async def _drain(self, start: str, handler: Handler, count: int) -> int:
        block = BLOCK_MILLISECONDS if start == ">" else None
        response: Any = await self._redis.xreadgroup(
            self._group, self._consumer, {CLOSED_CANDLE_STREAM: start}, count=count, block=block
        )
        handled = 0
        for _stream, messages in response or []:
            for message_id, fields in messages:
                body = fields.get(b"event") or fields.get("event")
                await handler(EventEnvelope.model_validate_json(body))
                await self._redis.xack(CLOSED_CANDLE_STREAM, self._group, message_id)
                handled += 1
        return handled
