import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid7

import pytest
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from websockets.asyncio.server import ServerConnection

from tests.conftest import make_settings
from tests.failure.fake_exchange import running, send_json, stay_open
from tests.fakes import FakeProvider, make_candle
from trading_intel.core.clock import Clock, FixedClock, SystemClock
from trading_intel.core.errors import ProviderError, ProviderHaltError
from trading_intel.data_providers.base import CandleSubscription, LinkDown, LinkUp
from trading_intel.data_providers.binance.provider import SPOT, BinanceProvider
from trading_intel.data_providers.binance.rest import BinanceRestClient
from trading_intel.database.repositories.candles import CandleRepository
from trading_intel.database.repositories.operations import (
    EventRepository,
    GapRepository,
    MarketRepository,
    RuleRepository,
    SnapshotRepository,
    SnapshotRow,
)
from trading_intel.database.repositories.reference import ReferenceRepository
from trading_intel.domain.base import DataOrigin
from trading_intel.domain.candles import ClosedCandle, FormingCandle, Timeframe
from trading_intel.domain.instruments import Instrument
from trading_intel.domain.market import OpenInterest, TopOfBook
from trading_intel.events.redis_transport import RedisEventBus
from trading_intel.market_data.gaps import GapRepairService
from trading_intel.market_data.health import FeedHealth, FeedState
from trading_intel.market_data.ingest import (
    Ingestor,
    IngestorAlreadyRunningError,
    IngestPlan,
    book_stream,
    kline_stream,
    single_instance_lock,
)
from trading_intel.market_data.instrument_rules import RuleSnapshotService
from trading_intel.market_data.reconcile import ReconcileService
from trading_intel.market_data.recovery import Downtime
from trading_intel.monitoring.coverage import CoverageService
from trading_intel.news_intelligence.official_sources import FeedItem, NewsArchive

pytestmark = pytest.mark.integration

START = datetime(2026, 1, 1, tzinfo=UTC)
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture
async def redis() -> AsyncIterator[Redis]:
    client: Redis = Redis.from_url(make_settings().redis_url.get_secret_value())
    await client.flushdb()
    yield client
    await client.aclose()


class OrderCheckingBus(RedisEventBus):
    """Fails a test if an event is published before its row is readable."""

    def __init__(self, redis: Redis, clock: Clock, candles: CandleRepository) -> None:
        super().__init__(redis, clock)
        self.candles = candles
        self.published: list[str] = []
        self.rows_at_publish: list[int] = []
        self.key: tuple[int, int] = (0, 0)

    async def publish_durable(
        self, topic: str, event_type: str, origin: DataOrigin, payload: BaseModel
    ) -> bool:
        self.published.append(topic)
        self.rows_at_publish.append(
            await self.candles.count(self.key[0], self.key[1], Timeframe.M1)
        )
        return await super().publish_durable(topic, event_type, origin, payload)


async def spot_btc(engine: AsyncEngine) -> tuple[int, Instrument]:
    listed = await ReferenceRepository(engine).provider_instruments("binance_spot")
    return listed[0].provider_id, listed[0].instrument


def build(
    provider: Any,
    provider_id: int,
    instrument: Instrument,
    engine: AsyncEngine,
    redis: Redis,
    clock: Clock,
    *,
    bus: RedisEventBus | None = None,
) -> Ingestor:
    candles = CandleRepository(engine)
    gaps = GapRepository(engine)
    plan = IngestPlan(
        "binance_spot",
        provider_id,
        [CandleSubscription(instrument=instrument, timeframe=Timeframe.M1)],
        [instrument],
    )
    health = FeedHealth(
        clock,
        ["spot"],
        [kline_stream(instrument.id, "1m"), book_stream(instrument.id)],
    )
    return Ingestor(
        plan,
        provider,
        candles,
        SnapshotRepository(engine),
        MarketRepository(engine),
        gaps,
        EventRepository(engine),
        bus or RedisEventBus(redis, clock),
        health,
        GapRepairService(provider, provider_id, candles, gaps, clock),
        ReconcileService(provider, provider_id, candles, clock),
        RuleSnapshotService(provider, provider_id, RuleRepository(engine), clock),
        clock,
    )


def forming(provider_id: int, instrument_id: int, open_time: datetime) -> FormingCandle:
    closed = make_candle(provider_id, instrument_id, Timeframe.M1, open_time)
    return FormingCandle(**closed.model_dump())


async def test_closed_candle_commits_before_it_is_published(
    ingest_engine: AsyncEngine, redis: Redis
) -> None:
    provider_id, instrument = await spot_btc(ingest_engine)
    clock = FixedClock(START + timedelta(minutes=1))
    candles = CandleRepository(ingest_engine)
    bus = OrderCheckingBus(redis, clock, candles)
    bus.key = (provider_id, instrument.id)
    ingestor = build(
        FakeProvider(provider_id), provider_id, instrument, ingest_engine, redis, clock, bus=bus
    )
    await ingestor.handle(
        make_candle(provider_id, instrument.id, Timeframe.M1, START, origin=DataOrigin.LIVE)
    )
    assert bus.rows_at_publish == [1]
    assert ingestor.counters.closed == 1


async def test_duplicate_delivery_creates_no_row_and_no_event(
    ingest_engine: AsyncEngine, redis: Redis
) -> None:
    provider_id, instrument = await spot_btc(ingest_engine)
    clock = FixedClock(START + timedelta(minutes=1))
    bus = OrderCheckingBus(redis, clock, CandleRepository(ingest_engine))
    bus.key = (provider_id, instrument.id)
    ingestor = build(
        FakeProvider(provider_id), provider_id, instrument, ingest_engine, redis, clock, bus=bus
    )
    candle = make_candle(provider_id, instrument.id, Timeframe.M1, START)
    await ingestor.handle(candle)
    await ingestor.handle(candle)
    assert len(bus.published) == 1
    assert ingestor.counters.duplicates == 1


async def test_forming_candle_is_never_stored(ingest_engine: AsyncEngine, redis: Redis) -> None:
    provider_id, instrument = await spot_btc(ingest_engine)
    clock = FixedClock(START)
    ingestor = build(
        FakeProvider(provider_id), provider_id, instrument, ingest_engine, redis, clock
    )
    await ingestor.handle(forming(provider_id, instrument.id, START))
    assert (
        await CandleRepository(ingest_engine).count(provider_id, instrument.id, Timeframe.M1) == 0
    )
    assert ingestor.counters.forming == 1


async def test_candle_from_the_future_is_rejected_with_a_record(
    ingest_engine: AsyncEngine, redis: Redis
) -> None:
    provider_id, instrument = await spot_btc(ingest_engine)
    clock = FixedClock(START)
    ingestor = build(
        FakeProvider(provider_id), provider_id, instrument, ingest_engine, redis, clock
    )
    await ingestor.handle(make_candle(provider_id, instrument.id, Timeframe.M1, START))
    assert (
        await CandleRepository(ingest_engine).count(provider_id, instrument.id, Timeframe.M1) == 0
    )
    assert ingestor.counters.rejected == 1
    async with ingest_engine.connect() as connection:
        message = (
            await connection.execute(
                text("SELECT message FROM system_events WHERE event_type = 'candle_rejected'")
            )
        ).scalar_one()
    assert message == "close_time_in_future"


async def test_startup_repairs_from_the_last_stored_candle(
    ingest_engine: AsyncEngine, redis: Redis
) -> None:
    provider_id, instrument = await spot_btc(ingest_engine)
    candles = CandleRepository(ingest_engine)
    await candles.insert([make_candle(provider_id, instrument.id, Timeframe.M1, START)])
    clock = FixedClock(START + timedelta(minutes=30, seconds=10))
    ingestor = build(
        FakeProvider(provider_id), provider_id, instrument, ingest_engine, redis, clock
    )
    await ingestor.recover("startup")
    assert await candles.count(provider_id, instrument.id, Timeframe.M1) == 30
    assert ingestor.health.status().state is not FeedState.RECOVERING


async def test_reconnect_triggers_a_repair_request(
    ingest_engine: AsyncEngine, redis: Redis
) -> None:
    provider_id, instrument = await spot_btc(ingest_engine)
    clock = FixedClock(START)
    ingestor = build(
        FakeProvider(provider_id), provider_id, instrument, ingest_engine, redis, clock
    )
    await ingestor.handle(LinkUp(route="spot", at=START))
    assert not ingestor._needs_repair.is_set()
    await ingestor.handle(LinkDown(route="spot", reason="drop", at=START))
    assert ingestor.health.status().state is FeedState.DISCONNECTED
    await ingestor.handle(LinkUp(route="spot", at=START))
    assert ingestor._needs_repair.is_set()


async def test_no_use_is_possible_while_recovering_after_sleep(
    ingest_engine: AsyncEngine, redis: Redis
) -> None:
    provider_id, instrument = await spot_btc(ingest_engine)
    candles = CandleRepository(ingest_engine)
    await candles.insert([make_candle(provider_id, instrument.id, Timeframe.M1, START)])
    clock = FixedClock(START + timedelta(minutes=1))
    states: list[bool] = []

    class Watching(FakeProvider):
        async def get_historical_candles(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
            states.append(ingestor.health.status().usable)
            async for candle in super().get_historical_candles(*args, **kwargs):
                yield candle

    ingestor = build(Watching(provider_id), provider_id, instrument, ingest_engine, redis, clock)
    clock.jump_wall_clock(1810)
    downtime = Downtime(START + timedelta(minutes=1), clock.now())
    await ingestor.recover("computer slept", downtime)
    assert states == [False]
    assert await candles.count(provider_id, instrument.id, Timeframe.M1) == 31
    async with ingest_engine.connect() as connection:
        data = (
            await connection.execute(
                text("SELECT data FROM system_events WHERE event_type = 'downtime'")
            )
        ).scalar_one()
    assert data["provider"] == "binance_spot"


async def test_redis_loss_does_not_stop_candle_storage_and_events_replay_later(
    ingest_engine: AsyncEngine, redis: Redis
) -> None:
    provider_id, instrument = await spot_btc(ingest_engine)
    clock = FixedClock(START + timedelta(minutes=1))
    dead: Redis = Redis.from_url("redis://127.0.0.1:1/0")
    ingestor = build(
        FakeProvider(provider_id),
        provider_id,
        instrument,
        ingest_engine,
        redis,
        clock,
        bus=RedisEventBus(dead, clock),
    )
    await ingestor.handle(make_candle(provider_id, instrument.id, Timeframe.M1, START))
    assert (
        await CandleRepository(ingest_engine).count(provider_id, instrument.id, Timeframe.M1) == 1
    )
    assert ingestor.counters.publish_failures == 1
    await dead.aclose()

    ingestor._bus = RedisEventBus(redis, clock)
    await ingestor._replay_missed()
    assert await redis.xlen("events:market.candle.closed") == 1


async def test_a_second_ingestor_cannot_start(ingest_engine: AsyncEngine) -> None:
    async with single_instance_lock(ingest_engine, 7001):
        with pytest.raises(IngestorAlreadyRunningError):
            async with single_instance_lock(ingest_engine, 7001):
                pytest.fail("the second holder must not get the lock")
    async with single_instance_lock(ingest_engine, 7001):
        pass  # A clean stop released it.


async def test_snapshot_rows_are_written_for_finished_minutes(
    ingest_engine: AsyncEngine, redis: Redis
) -> None:
    provider_id, instrument = await spot_btc(ingest_engine)
    clock = FixedClock(START)
    ingestor = build(
        FakeProvider(provider_id), provider_id, instrument, ingest_engine, redis, clock
    )
    await ingestor.handle(
        TopOfBook(
            provider_id=provider_id,
            instrument_id=instrument.id,
            bid_price=Decimal(100),
            bid_quantity=Decimal(1),
            ask_price=Decimal(101),
            ask_quantity=Decimal(1),
            received_at=START,
        )
    )
    clock.advance(61)
    await ingestor._flush_snapshots()
    minutes = await SnapshotRepository(ingest_engine).spread_minutes(
        provider_id, instrument.id, START, START + timedelta(minutes=1)
    )
    assert minutes == 1


async def test_end_to_end_from_a_websocket_frame_to_postgres_and_redis(
    ingest_engine: AsyncEngine, redis: Redis
) -> None:
    """Real frames, a real socket, real PostgreSQL and real Redis."""
    provider_id, instrument = await spot_btc(ingest_engine)
    frames = json.loads((FIXTURES / "binance_spot/stream_frames.json").read_text())
    closing = next(f for f in frames if f["data"].get("k", {}).get("x") is True)

    async def behaviour(connection: ServerConnection, _: int) -> None:
        for frame in frames:
            await send_json(connection, frame)
        await send_json(connection, closing)  # Duplicate delivery.
        await stay_open(connection)

    clock = SystemClock()
    async with running(behaviour) as exchange:
        rest = BinanceRestClient("https://binance.test", SPOT.allowed_paths, 100, clock)
        provider = BinanceProvider(
            SPOT, provider_id, {instrument.id: "BTCUSDT"}, rest, exchange.url, clock
        )
        ingestor = build(provider, provider_id, instrument, ingest_engine, redis, clock)
        stream = provider.stream_market(
            [CandleSubscription(instrument=instrument, timeframe=Timeframe.M1)], [instrument]
        )
        handled = 0
        async for event in stream:
            await ingestor.handle(event)
            handled += 1
            if handled == len(frames) + 2:
                break
    stored: list[ClosedCandle] = await CandleRepository(ingest_engine).page(
        provider_id, instrument.id, Timeframe.M1, 10
    )
    assert len(stored) == 1
    assert stored[0].close == Decimal(closing["data"]["k"]["c"])
    assert stored[0].data_origin is DataOrigin.LIVE
    assert ingestor.counters.duplicates == 1
    assert await redis.xlen("events:market.candle.closed") == 1


async def test_open_interest_history_fills_snapshots_without_erasing_spread(
    ingest_engine: AsyncEngine, redis: Redis
) -> None:
    provider_id, instrument = await spot_btc(ingest_engine)
    now = START + timedelta(hours=1)
    clock = FixedClock(now)
    snapshots = SnapshotRepository(ingest_engine)
    base = SnapshotRow(
        provider_id=provider_id,
        instrument_id=instrument.id,
        minute_start=START + timedelta(minutes=5),
        best_bid=Decimal(100),
        best_ask=Decimal(101),
        spread_min=Decimal(1),
        spread_mean=Decimal(1),
        spread_max=Decimal(1),
        spread_last=Decimal(1),
        sample_count=10,
        crossed_book_count=0,
        data_origin=DataOrigin.LIVE,
        received_at=START,
    )
    await snapshots.upsert(base)

    class Derivatives(FakeProvider):
        async def get_open_interest_history(self, target: Instrument, start: datetime) -> Any:
            for minutes in (0, 5, 10):
                at = START + timedelta(minutes=minutes)
                yield OpenInterest(
                    provider_id=provider_id,
                    instrument_id=target.id,
                    open_interest=Decimal(500 + minutes),
                    event_time=at,
                    received_at=now,
                )

    ingestor = build(Derivatives(provider_id), provider_id, instrument, ingest_engine, redis, clock)
    await ingestor._repair_open_interest(Derivatives(provider_id), instrument)
    async with ingest_engine.connect() as connection:
        rows = (
            await connection.execute(
                text(
                    "SELECT open_interest, sample_count FROM market_snapshots ORDER BY minute_start"
                )
            )
        ).all()
    assert [row.open_interest for row in rows] == [Decimal(500), Decimal(505), Decimal(510)]
    assert rows[1].sample_count == 10


async def test_open_interest_refills_the_month_even_when_recent_rows_exist(
    ingest_engine: AsyncEngine, redis: Redis
) -> None:
    """Regression: live rows hid the empty month before them."""
    provider_id, instrument = await spot_btc(ingest_engine)
    now = START + timedelta(days=40)
    snapshots = SnapshotRepository(ingest_engine)
    await snapshots.upsert(
        SnapshotRow(
            provider_id=provider_id,
            instrument_id=instrument.id,
            minute_start=now - timedelta(minutes=5),
            best_bid=None,
            best_ask=None,
            spread_min=None,
            spread_mean=None,
            spread_max=None,
            spread_last=None,
            sample_count=0,
            crossed_book_count=0,
            open_interest=Decimal(1),
            data_origin=DataOrigin.LIVE,
            received_at=now,
        )
    )
    requested: list[datetime] = []

    class Derivatives(FakeProvider):
        async def get_open_interest_history(self, target: Instrument, start: datetime) -> Any:
            requested.append(start)
            return
            yield

    ingestor = build(
        Derivatives(provider_id), provider_id, instrument, ingest_engine, redis, FixedClock(now)
    )
    await ingestor._repair_open_interest(Derivatives(provider_id), instrument)
    assert requested == [now - timedelta(days=29)]


async def test_coverage_reports_downtime_repairs_and_lost_spread(
    ingest_engine: AsyncEngine, redis: Redis
) -> None:
    provider_id, instrument = await spot_btc(ingest_engine)
    candles = CandleRepository(ingest_engine)
    await candles.insert([make_candle(provider_id, instrument.id, Timeframe.M1, START)])
    clock = FixedClock(START + timedelta(minutes=1))
    ingestor = build(
        FakeProvider(provider_id), provider_id, instrument, ingest_engine, redis, clock
    )
    clock.jump_wall_clock(1810)
    await ingestor.recover("computer slept", Downtime(START + timedelta(minutes=1), clock.now()))
    events = EventRepository(ingest_engine)
    coverage = CoverageService(
        ReferenceRepository(ingest_engine),
        candles,
        GapRepository(ingest_engine),
        SnapshotRepository(ingest_engine),
        events,
    )
    report = await coverage.report(
        START - timedelta(minutes=1), datetime.now(UTC) + timedelta(minutes=1)
    )
    entry = next(i for i in report.instruments if i.instrument_id == instrument.id)
    assert entry.provider == "binance_spot"
    assert entry.gaps_repaired == 1
    assert entry.spread_minutes_recorded == 0
    assert entry.spread_minutes_lost == entry.candles_expected
    assert [d.reason for d in report.downtime] == ["computer slept"]


async def test_archive_keeps_the_first_sighting_of_each_url(ingest_engine: AsyncEngine) -> None:
    async with ingest_engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT p.id AS provider, s.id AS source FROM providers p "
                    "JOIN news_sources s ON s.provider_id = p.id"
                )
            )
        ).one()
    archive = NewsArchive(ingest_engine, row.provider, row.source)
    item = FeedItem("Headline", f"https://example.test/{uuid7()}", None, START)
    assert await archive.store([item], START) == 1
    assert await archive.store([item], START + timedelta(days=1)) == 0


class FlakyCandles(CandleRepository):
    """Fails like a restarting database, then recovers."""

    failures = 0

    async def insert(self, candles: Any, run_id: Any = None) -> int:
        if self.failures > 0:
            self.failures -= 1
            raise ConnectionRefusedError("database restarting")
        return await super().insert(candles, run_id)


async def test_a_short_database_outage_is_ridden_out(
    ingest_engine: AsyncEngine, redis: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider_id, instrument = await spot_btc(ingest_engine)
    clock = FixedClock(START + timedelta(minutes=1))
    ingestor = build(
        FakeProvider(provider_id), provider_id, instrument, ingest_engine, redis, clock
    )
    flaky = FlakyCandles(ingest_engine)
    flaky.failures = 2
    ingestor._candles = flaky

    async def no_wait(_: float) -> None:
        return None

    monkeypatch.setattr("trading_intel.market_data.ingest.asyncio.sleep", no_wait)
    await ingestor.handle(make_candle(provider_id, instrument.id, Timeframe.M1, START))
    assert ingestor.counters.closed == 1
    assert await flaky.count(provider_id, instrument.id, Timeframe.M1) == 1


async def test_a_long_database_outage_requests_repair_instead_of_crashing(
    ingest_engine: AsyncEngine, redis: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider_id, instrument = await spot_btc(ingest_engine)
    clock = FixedClock(START + timedelta(minutes=1))
    ingestor = build(
        FakeProvider(provider_id), provider_id, instrument, ingest_engine, redis, clock
    )
    flaky = FlakyCandles(ingest_engine)
    flaky.failures = 10_000
    ingestor._candles = flaky

    async def time_passes(seconds: float) -> None:
        clock.advance(30)

    monkeypatch.setattr("trading_intel.market_data.ingest.asyncio.sleep", time_passes)
    await ingestor.handle(make_candle(provider_id, instrument.id, Timeframe.M1, START))
    assert ingestor.counters.store_failures == 1
    assert ingestor._needs_repair.is_set()


async def test_a_failed_recovery_stays_unusable_and_retries(
    ingest_engine: AsyncEngine, redis: Redis
) -> None:
    provider_id, instrument = await spot_btc(ingest_engine)
    clock = FixedClock(START + timedelta(minutes=1))

    class Failing(FakeProvider):
        async def get_historical_candles(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
            raise ProviderError("network down")
            yield

    ingestor = build(Failing(provider_id), provider_id, instrument, ingest_engine, redis, clock)
    await ingestor._recover_safely("startup")
    assert ingestor.health.status().state is FeedState.RECOVERING
    assert ingestor._needs_repair.is_set()


async def test_a_refusal_by_the_provider_stops_recovery_for_good(
    ingest_engine: AsyncEngine, redis: Redis
) -> None:
    provider_id, instrument = await spot_btc(ingest_engine)
    clock = FixedClock(START + timedelta(minutes=1))

    class Refused(FakeProvider):
        async def get_historical_candles(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
            raise ProviderHaltError("Binance refuses this location")
            yield

    ingestor = build(Refused(provider_id), provider_id, instrument, ingest_engine, redis, clock)
    with pytest.raises(ProviderHaltError):
        await ingestor._recover_safely("startup")


async def test_a_stream_outage_is_recorded_as_downtime(
    ingest_engine: AsyncEngine, redis: Redis
) -> None:
    provider_id, instrument = await spot_btc(ingest_engine)
    clock = FixedClock(START)
    ingestor = build(
        FakeProvider(provider_id), provider_id, instrument, ingest_engine, redis, clock
    )
    await ingestor.handle(LinkDown(route="spot", reason="drop", at=START))
    clock.advance(90)
    await ingestor.handle(LinkUp(route="spot", at=clock.now()))
    assert ingestor._down_since == START
    maintaining = asyncio.create_task(ingestor.maintain())
    await asyncio.sleep(0.2)
    maintaining.cancel()
    await asyncio.gather(maintaining, return_exceptions=True)
    periods = await EventRepository(ingest_engine).downtime(
        datetime(2000, 1, 1, tzinfo=UTC), datetime(2100, 1, 1, tzinfo=UTC)
    )
    assert [p["reason"] for p in periods] == ["stream reconnected"]
    assert periods[0]["start"] == START.isoformat()


async def test_restart_after_a_crash_reports_the_time_away(
    ingest_engine: AsyncEngine, redis: Redis
) -> None:
    provider_id, instrument = await spot_btc(ingest_engine)
    await CandleRepository(ingest_engine).insert(
        [make_candle(provider_id, instrument.id, Timeframe.M1, START)]
    )
    clock = FixedClock(START + timedelta(minutes=30))
    ingestor = build(
        FakeProvider(provider_id), provider_id, instrument, ingest_engine, redis, clock
    )
    downtime = await ingestor._time_since_last_run()
    assert downtime is not None
    assert downtime.start == START + timedelta(minutes=1)


async def test_a_quick_restart_is_not_downtime(ingest_engine: AsyncEngine, redis: Redis) -> None:
    provider_id, instrument = await spot_btc(ingest_engine)
    await CandleRepository(ingest_engine).insert(
        [make_candle(provider_id, instrument.id, Timeframe.M1, START)]
    )
    clock = FixedClock(START + timedelta(minutes=2))
    ingestor = build(
        FakeProvider(provider_id), provider_id, instrument, ingest_engine, redis, clock
    )
    assert await ingestor._time_since_last_run() is None
