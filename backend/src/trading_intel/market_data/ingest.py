"""The live path. Closed candles reach PostgreSQL before anything is published."""

import asyncio
import contextlib
import statistics
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta

import asyncpg
import structlog
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from trading_intel.core.clock import Clock
from trading_intel.core.errors import AppError, ProviderHaltError
from trading_intel.data_providers.base import (
    CandleSubscription,
    DerivativesCapable,
    LinkDown,
    LinkUp,
    MarketDataProvider,
    MarketEvent,
    MarketEventRejected,
)
from trading_intel.database.repositories.candles import CandleRepository
from trading_intel.database.repositories.operations import (
    EventRepository,
    GapRepository,
    MarketRepository,
    SnapshotRepository,
    SnapshotRow,
)
from trading_intel.domain.base import DataOrigin
from trading_intel.domain.candles import ClosedCandle, FormingCandle, Timeframe
from trading_intel.domain.events import (
    MARKET_CANDLE,
    MARKET_PRICE,
    MARKET_STATUS,
    MarketPricePayload,
    MarketStatusPayload,
    candle_payload,
    plain,
)
from trading_intel.domain.instruments import Instrument
from trading_intel.domain.market import LiquidationSample, MarkPrice, TopOfBook
from trading_intel.events.redis_transport import RedisEventBus
from trading_intel.market_data.gaps import GapRepairService
from trading_intel.market_data.health import FeedHealth
from trading_intel.market_data.instrument_rules import REFRESH_SECONDS, RuleSnapshotService
from trading_intel.market_data.reconcile import SWEEP_SECONDS, ReconcileService
from trading_intel.market_data.recovery import Downtime, SleepDetector
from trading_intel.market_data.snapshots import MinuteAggregator
from trading_intel.market_data.validate import rejection_reason

log = structlog.get_logger(__name__)

TICK_SECONDS = 5.0
PRICE_PUBLISH_SECONDS = 0.25
FORMING_PUBLISH_SECONDS = 1.0
SKEW_SECONDS = 60
OPEN_INTEREST_SECONDS = 60
FUNDING_SECONDS = 600
SETTLE_SECONDS = 3  # A candle that has just closed may still be in flight.
FIRST_RUN_LOOKBACK = 10
LATENCY_SAMPLES = 5000
OPEN_INTEREST_HISTORY = timedelta(days=29)
WRITE_RETRY_SECONDS = 60.0
TRANSIENT_DATABASE_ERRORS = (DBAPIError, OSError, asyncpg.PostgresError, asyncpg.InterfaceError)


class IngestorAlreadyRunningError(AppError):
    code = "ingestor_already_running"


def topic_price(provider: str, instrument_id: int) -> str:
    return f"{MARKET_PRICE}:{provider}:{instrument_id}"


def topic_candle(provider: str, instrument_id: int, timeframe: str) -> str:
    return f"{MARKET_CANDLE}:{provider}:{instrument_id}:{timeframe}"


def topic_status(provider: str) -> str:
    return f"{MARKET_STATUS}:{provider}"


def kline_stream(instrument_id: int, timeframe: str) -> str:
    return f"kline:{instrument_id}:{timeframe}"


def book_stream(instrument_id: int) -> str:
    return f"book:{instrument_id}"


def mark_stream(instrument_id: int) -> str:
    return f"mark:{instrument_id}"


@dataclass
class Counters:
    closed: int = 0
    duplicates: int = 0
    forming: int = 0
    book: int = 0
    rejected: int = 0
    publish_failures: int = 0
    store_failures: int = 0


@dataclass(frozen=True)
class IngestPlan:
    provider_code: str
    provider_id: int
    subscriptions: Sequence[CandleSubscription]
    book_instruments: Sequence[Instrument]
    mark_instruments: Sequence[Instrument] = ()
    liquidation_instruments: Sequence[Instrument] = ()

    @property
    def instruments(self) -> list[Instrument]:
        seen = {s.instrument.id: s.instrument for s in self.subscriptions}
        seen.update({i.id: i for i in self.book_instruments})
        return list(seen.values())


class Ingestor:
    def __init__(
        self,
        plan: IngestPlan,
        provider: MarketDataProvider,
        candles: CandleRepository,
        snapshots: SnapshotRepository,
        market: MarketRepository,
        gaps: GapRepository,
        events: EventRepository,
        bus: RedisEventBus,
        health: FeedHealth,
        repair: GapRepairService,
        reconcile: ReconcileService,
        rules: RuleSnapshotService,
        clock: Clock,
    ) -> None:
        self._plan = plan
        self._provider = provider
        self._candles = candles
        self._snapshots = snapshots
        self._market = market
        self._gaps = gaps
        self._events = events
        self._bus = bus
        self.health = health
        self._repair = repair
        self._reconcile = reconcile
        self._rules = rules
        self._clock = clock
        self._aggregator = MinuteAggregator(plan.provider_id)
        self._sleep_detector = SleepDetector(clock)
        self._last_price: dict[int, float] = {}
        self._last_forming: dict[str, float] = {}
        self._was_down = False
        self._needs_repair = asyncio.Event()
        self._replay_from: datetime | None = None
        self.counters = Counters()
        self.latencies: deque[float] = deque(maxlen=LATENCY_SAMPLES)

    # Events ---------------------------------------------------------------------------------

    async def handle(self, event: MarketEvent) -> None:
        match event:
            case ClosedCandle():
                await self._on_closed(event)
            case FormingCandle():
                await self._on_forming(event)
            case TopOfBook():
                await self._on_book(event)
            case MarkPrice():
                self.health.saw(mark_stream(event.instrument_id))
                self._aggregator.add_mark(event)
            case LiquidationSample():
                await self._with_retry(lambda: self._market.insert_liquidation(event))
            case LinkUp():
                self.health.link_up(event.route)
                if self._was_down:
                    self._was_down = False
                    self._needs_repair.set()
            case LinkDown():
                self.health.link_down(event.route, event.reason)
                self._was_down = True
            case MarketEventRejected():
                self.counters.rejected += 1
                log.warning("frame_rejected", route=event.route, reason=event.reason)

    async def _on_closed(self, candle: ClosedCandle) -> None:
        self.health.saw(kline_stream(candle.instrument_id, candle.timeframe.value))
        reason = rejection_reason(candle, self._clock.now())
        if reason:
            self.counters.rejected += 1
            await self._events.record(
                "warning",
                "ingestor",
                "candle_rejected",
                reason,
                {"open_time": candle.open_time.isoformat(), "timeframe": candle.timeframe.value},
            )
            return
        try:
            added = await self._with_retry(lambda: self._candles.insert([candle]))
        except TRANSIENT_DATABASE_ERRORS as error:
            # The candle is still at the provider, so repair recovers it once the database is back.
            log.error("candle_store_failed", error=type(error).__name__)
            self.counters.store_failures += 1
            self._needs_repair.set()
            return
        if added == 0:
            self.counters.duplicates += 1
            return
        # The commit above has finished, so a consumer can always read what it is told about.
        self.latencies.append((self._clock.now() - candle.close_time).total_seconds())
        self.counters.closed += 1
        await self._publish_closed(candle)

    async def _publish_closed(self, candle: ClosedCandle) -> None:
        topic = topic_candle(self._plan.provider_code, candle.instrument_id, candle.timeframe.value)
        payload = candle_payload(self._plan.provider_code, candle)
        if not await self._bus.publish_durable(topic, MARKET_CANDLE, candle.data_origin, payload):
            self.counters.publish_failures += 1
            if self._replay_from is None:
                self._replay_from = candle.open_time

    async def _on_forming(self, candle: FormingCandle) -> None:
        self.counters.forming += 1
        self.health.saw(kline_stream(candle.instrument_id, candle.timeframe.value))
        topic = topic_candle(self._plan.provider_code, candle.instrument_id, candle.timeframe.value)
        now = self._clock.monotonic()
        if now - self._last_forming.get(topic, -1e9) < FORMING_PUBLISH_SECONDS:
            return
        self._last_forming[topic] = now
        payload = candle_payload(self._plan.provider_code, candle)
        await self._bus.publish_latest(topic, MARKET_CANDLE, candle.data_origin, payload)

    async def _on_book(self, book: TopOfBook) -> None:
        self.counters.book += 1
        self.health.saw(book_stream(book.instrument_id))
        self._aggregator.add_book(book)
        now = self._clock.monotonic()
        if now - self._last_price.get(book.instrument_id, -1e9) < PRICE_PUBLISH_SECONDS:
            return
        self._last_price[book.instrument_id] = now
        await self._bus.publish_latest(
            topic_price(self._plan.provider_code, book.instrument_id),
            MARKET_PRICE,
            DataOrigin.LIVE,
            MarketPricePayload(
                provider=self._plan.provider_code,
                instrument_id=book.instrument_id,
                bid=plain(book.bid_price),
                ask=plain(book.ask_price),
                received_at=book.received_at,
            ),
        )

    async def _with_retry[T](self, operation: Callable[[], Awaitable[T]]) -> T:
        """Ride out a short database outage, such as a restart. Bad data is not retried."""
        delay = 0.5
        deadline = self._clock.monotonic() + WRITE_RETRY_SECONDS
        while True:
            try:
                return await operation()
            except IntegrityError:
                raise
            except TRANSIENT_DATABASE_ERRORS as error:
                if self._clock.monotonic() >= deadline:
                    raise
                log.warning("database_retry", error=type(error).__name__, delay=delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 5.0)

    # Repair ---------------------------------------------------------------------------------

    async def repair_to_now(self, cause: str = "ingest_failure") -> None:
        """Repair every timeframe from its last stored candle to the latest closed one."""
        safe_now = self._clock.now() - timedelta(seconds=SETTLE_SECONDS)
        for subscription in self._plan.subscriptions:
            instrument, timeframe = subscription.instrument, subscription.timeframe
            end = timeframe.floor(safe_now)
            latest = await self._candles.latest_open_time(
                self._plan.provider_id, instrument.id, timeframe
            )
            start = (
                timeframe.next_open(latest)
                if latest is not None
                else end - timeframe.delta * FIRST_RUN_LOOKBACK
            )
            if start < end:
                await self._repair.repair(instrument, timeframe, start, end, cause)

    async def recover(self, reason: str, downtime: Downtime | None = None) -> None:
        """Repair in a fixed order, and report healthy only when repaired."""
        self.health.begin_recovery(reason)
        await self._publish_status()
        if downtime is not None:
            await self._events.record(
                "warning",
                "ingestor",
                "downtime",
                reason,
                {
                    "provider": self._plan.provider_code,
                    "start": downtime.start.isoformat(),
                    "end": downtime.end.isoformat(),
                },
            )
        await self.repair_to_now()
        await self._repair_derivatives()
        await self._refresh_open_gaps()
        self.health.end_recovery()
        await self._publish_status()

    async def _recover_safely(self, reason: str, downtime: Downtime | None = None) -> None:
        """A failed repair leaves the feed RECOVERING and is tried again on a later tick."""
        try:
            await self.recover(reason, downtime)
        except ProviderHaltError:
            raise
        except Exception as error:
            log.warning("recovery_failed", reason=reason, error=type(error).__name__)
            self._needs_repair.set()

    async def _repair_derivatives(self) -> None:
        provider = self._provider
        if not provider.capabilities.funding or not isinstance(provider, DerivativesCapable):
            return
        for instrument in self._plan.mark_instruments:
            latest = await self._market.latest_funding_time(self._plan.provider_id, instrument.id)
            start = (latest or self._clock.now() - timedelta(days=30)) + timedelta(milliseconds=1)
            rows = [row async for row in provider.get_funding_history(instrument, start)]
            await self._market.insert_funding(rows)
            await self._repair_open_interest(provider, instrument)

    async def _repair_open_interest(
        self, provider: DerivativesCapable, instrument: Instrument
    ) -> None:
        """Binance keeps about a month, so anything older cannot be refilled."""
        now = self._clock.now()
        latest = await self._snapshots.latest_open_interest_minute(
            self._plan.provider_id, instrument.id
        )
        oldest_available = now - OPEN_INTEREST_HISTORY
        start = max(latest + timedelta(minutes=5), oldest_available) if latest else oldest_available
        rows = [
            SnapshotRow(
                provider_id=self._plan.provider_id,
                instrument_id=instrument.id,
                minute_start=Timeframe.M1.floor(item.event_time),
                best_bid=None,
                best_ask=None,
                spread_min=None,
                spread_mean=None,
                spread_max=None,
                spread_last=None,
                sample_count=0,
                crossed_book_count=0,
                open_interest=item.open_interest,
                data_origin=DataOrigin.BACKFILL,
                received_at=item.received_at,
            )
            async for item in provider.get_open_interest_history(instrument, start)
        ]
        await self._snapshots.upsert_many(rows)

    async def _refresh_open_gaps(self) -> None:
        unresolved = await self._gaps.list(
            provider_id=self._plan.provider_id, states=("detected", "repairing")
        )
        self.health.open_gaps = len(unresolved)

    # Maintenance ----------------------------------------------------------------------------

    async def _publish_status(self) -> None:
        status = self.health.status()
        await self._bus.publish_latest(
            topic_status(self._plan.provider_code),
            MARKET_STATUS,
            DataOrigin.LIVE,
            MarketStatusPayload(
                provider=self._plan.provider_code,
                state=status.state.value,
                reasons=list(status.reasons),
                last_event_at=status.last_event_at,
                lag_seconds=status.lag_seconds,
                open_gaps=status.open_gaps,
                clock_skew_ms=status.clock_skew_ms,
            ),
        )

    async def _flush_snapshots(self) -> None:
        rows = self._aggregator.flush(self._clock.now())
        await self._with_retry(lambda: self._snapshots.upsert_many(rows))

    async def _replay_missed(self) -> None:
        """Send closed candles that Redis missed, once it is back."""
        if self._replay_from is None or not await self._bus.is_available():
            return
        since, self._replay_from = self._replay_from, None
        end = self._clock.now()
        for subscription in self._plan.subscriptions:
            missed = await self._candles.range(
                self._plan.provider_id,
                subscription.instrument.id,
                subscription.timeframe,
                since,
                end,
            )
            for candle in missed:
                await self._publish_closed(candle)

    async def _sweep(self) -> None:
        for subscription in self._plan.subscriptions:
            result = await self._reconcile.sweep(subscription.instrument, subscription.timeframe)
            if result.recovered or result.mismatched:
                log.info(
                    "sweep_found_differences",
                    instrument=subscription.instrument.symbol,
                    timeframe=subscription.timeframe.value,
                    recovered=result.recovered,
                    mismatched=result.mismatched,
                )

    async def _update_skew(self) -> None:
        server_time = await self._provider.get_server_time()
        skew = (server_time - self._clock.now()).total_seconds() * 1000
        self.health.clock_skew_ms = skew

    async def _update_open_interest(self) -> None:
        provider = self._provider
        if not provider.capabilities.open_interest or not isinstance(provider, DerivativesCapable):
            return
        for instrument in self._plan.mark_instruments:
            self._aggregator.add_open_interest(await provider.get_open_interest(instrument))

    async def maintain(self) -> None:
        """Run periodic work until cancelled. A failed step is logged and retried later."""
        schedule: dict[str, float] = {}

        async def every(name: str, seconds: float, step: Callable[[], Awaitable[object]]) -> None:
            now = self._clock.monotonic()
            if now - schedule.get(name, -1e9) < seconds:
                return
            schedule[name] = now
            try:
                await step()
            except ProviderHaltError:
                raise
            except Exception as error:
                log.warning("maintenance_step_failed", step=name, error=type(error).__name__)

        while True:
            downtime = self._sleep_detector.check()
            if downtime is not None:
                await self._recover_safely("computer slept", downtime)
            if self._needs_repair.is_set():
                self._needs_repair.clear()
                await self._recover_safely("stream reconnected")
            await every("snapshots", TICK_SECONDS, self._flush_snapshots)
            await every("status", TICK_SECONDS, self._publish_status)
            await every("replay", 30, self._replay_missed)
            await every("sweep", SWEEP_SECONDS, self._sweep)
            await every("skew", SKEW_SECONDS, self._update_skew)
            await every("gaps", SKEW_SECONDS, self._refresh_open_gaps)
            await every(
                "rules", REFRESH_SECONDS, lambda: self._rules.refresh(self._plan.instruments)
            )
            await every("open_interest", OPEN_INTEREST_SECONDS, self._update_open_interest)
            await every("funding", FUNDING_SECONDS, self._repair_derivatives)
            await asyncio.sleep(TICK_SECONDS)

    async def consume(self) -> None:
        stream = self._provider.stream_market(
            self._plan.subscriptions,
            self._plan.book_instruments,
            mark_instruments=self._plan.mark_instruments,
            liquidation_instruments=self._plan.liquidation_instruments,
        )
        async for event in stream:
            await self.handle(event)

    async def run(self) -> None:
        """Start the stream first, so nothing is missed while startup repair runs."""
        consumer = asyncio.create_task(self.consume())
        maintainer: asyncio.Task[None] | None = None
        try:
            await self._recover_safely("startup")
            maintainer = asyncio.create_task(self.maintain())
            done, _ = await asyncio.wait(
                {consumer, maintainer}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                task.result()
        finally:
            consumer.cancel()
            if maintainer:
                maintainer.cancel()
            await asyncio.gather(consumer, return_exceptions=True)

    def latency_p95(self) -> float | None:
        if len(self.latencies) < 20:
            return None
        return statistics.quantiles(self.latencies, n=20)[18]


@asynccontextmanager
async def single_instance_lock(engine: AsyncEngine, key: int) -> AsyncIterator[None]:
    """Hold an advisory lock while running, so a second ingestor cannot start.

    PostgreSQL releases it if this process dies, and it is released here on a clean stop,
    because the connection otherwise returns to the pool with the lock still held.
    """
    async with engine.connect() as connection:
        result = await connection.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": key})
        if not result.scalar_one():
            raise IngestorAlreadyRunningError(f"another ingestor holds lock {key}")
        await connection.commit()
        try:
            yield
        finally:
            # If PostgreSQL restarted, the lock went with the old connection.
            with contextlib.suppress(*TRANSIENT_DATABASE_ERRORS):
                await connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                await connection.commit()
