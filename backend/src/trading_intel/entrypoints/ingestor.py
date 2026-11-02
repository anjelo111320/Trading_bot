"""Run live market data. One process serves every provider, to save memory on 8 GB."""

import argparse
import asyncio
import signal
from typing import Final

import structlog
from anthropic import AsyncAnthropic
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from trading_intel.core.clock import SystemClock
from trading_intel.core.logging import configure_logging
from trading_intel.core.settings import Settings, load_settings
from trading_intel.data_providers.base import CandleSubscription
from trading_intel.database.engine import create_engine
from trading_intel.database.repositories.candles import CandleRepository
from trading_intel.database.repositories.news import NewsRepository
from trading_intel.database.repositories.operations import (
    EventRepository,
    GapRepository,
    MarketRepository,
    RuleRepository,
    SnapshotRepository,
)
from trading_intel.database.repositories.reference import ReferenceRepository
from trading_intel.domain.candles import Timeframe
from trading_intel.entrypoints.wiring import BINANCE_SPOT, BINANCE_USDM, SYNTHETIC, build_provider
from trading_intel.events.redis_transport import RedisEventBus
from trading_intel.market_data.gaps import GapRepairService
from trading_intel.market_data.health import FeedHealth
from trading_intel.market_data.ingest import (
    Ingestor,
    IngestPlan,
    book_stream,
    kline_stream,
    mark_stream,
    single_instance_lock,
)
from trading_intel.market_data.instrument_rules import RuleSnapshotService
from trading_intel.market_data.reconcile import ReconcileService
from trading_intel.news_intelligence.classifier import ClaudeClassifier
from trading_intel.news_intelligence.official_sources import NewsArchive, OfficialSourceCollector
from trading_intel.news_intelligence.pipeline import NewsPipeline

log = structlog.get_logger(__name__)

NEWS_SECONDS: Final = 900
LOCK_KEYS: Final = {BINANCE_SPOT: 7101, BINANCE_USDM: 7102, SYNTHETIC: 7103}
ROUTES: Final = {
    BINANCE_SPOT: ("spot",),
    BINANCE_USDM: ("market", "public"),
    SYNTHETIC: ("synthetic",),
}


async def build_ingestor(
    code: str, settings: Settings, engine: AsyncEngine, redis: Redis
) -> Ingestor:
    clock = SystemClock()
    listed = await ReferenceRepository(engine).provider_instruments(code)
    provider = build_provider(code, settings, clock, listed)
    provider_id = listed[0].provider_id
    instruments = [item.instrument for item in listed]
    subscriptions = [
        CandleSubscription(instrument=instrument, timeframe=timeframe)
        for instrument in instruments
        for timeframe in Timeframe
    ]
    derivatives = instruments if provider.capabilities.funding else []
    plan = IngestPlan(
        code,
        provider_id,
        subscriptions,
        instruments,
        mark_instruments=derivatives,
        liquidation_instruments=derivatives if provider.capabilities.liquidations else [],
    )
    expected = [kline_stream(s.instrument.id, s.timeframe.value) for s in subscriptions]
    expected += [book_stream(i.id) for i in instruments]
    expected += [mark_stream(i.id) for i in derivatives]
    candles = CandleRepository(engine)
    gaps = GapRepository(engine)
    return Ingestor(
        plan,
        provider,
        candles,
        SnapshotRepository(engine),
        MarketRepository(engine),
        gaps,
        EventRepository(engine),
        RedisEventBus(redis, clock),
        FeedHealth(clock, ROUTES[code], expected),
        GapRepairService(provider, provider_id, candles, gaps, clock),
        ReconcileService(provider, provider_id, candles, clock),
        RuleSnapshotService(provider, provider_id, RuleRepository(engine), clock),
        clock,
    )


async def build_collector(engine: AsyncEngine) -> OfficialSourceCollector:
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    """SELECT p.id AS provider, s.id AS source FROM providers p
                       JOIN news_sources s ON s.provider_id = p.id
                       WHERE p.code = 'federal_reserve'"""
                )
            )
        ).one()
    return OfficialSourceCollector(NewsArchive(engine, row.provider, row.source), SystemClock())


async def run_news(settings: Settings, engine: AsyncEngine) -> None:
    """Classification stays off until a key is configured. Everything else still runs."""
    key = settings.anthropic_api_key.get_secret_value()
    classifier = ClaudeClassifier(AsyncAnthropic(api_key=key)) if key else None
    listed = await ReferenceRepository(engine).provider_instruments("binance_usdm")
    pipeline = NewsPipeline(
        NewsRepository(engine),
        [item.instrument for item in listed],
        SystemClock(),
        classifier,
    )
    while True:
        try:
            result = await pipeline.run_once()
            if result.clustered or result.classified:
                log.info("news_processed", clustered=result.clustered, classified=result.classified)
        except Exception as error:
            log.warning("news_pipeline_failed", error=type(error).__name__)
        await asyncio.sleep(NEWS_SECONDS)


async def run_one(code: str, settings: Settings, engine: AsyncEngine, redis: Redis) -> None:
    async with single_instance_lock(engine, LOCK_KEYS[code]):
        ingestor = await build_ingestor(code, settings, engine, redis)
        log.info("ingestor_started", provider=code)
        await ingestor.run()


async def run(codes: list[str]) -> None:
    settings = load_settings()
    configure_logging(settings.log_level, settings.secret_values())
    engine = create_engine(settings.ingest_database_url, pool_size=8)
    redis: Redis = Redis.from_url(settings.redis_url.get_secret_value())
    tasks = [asyncio.create_task(run_one(code, settings, engine, redis)) for code in codes]
    tasks.append(asyncio.create_task((await build_collector(engine)).run()))
    tasks.append(asyncio.create_task(run_news(settings, create_engine(settings.database_url))))

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for number in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(number, stop.set)
    stopping = asyncio.create_task(stop.wait())
    try:
        await asyncio.wait({*tasks, stopping}, return_when=asyncio.FIRST_COMPLETED)
        for task in tasks:
            if task.done():
                task.result()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await redis.aclose()
        await engine.dispose()
        log.info("ingestor_stopped")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--providers", nargs="+", default=[BINANCE_SPOT, BINANCE_USDM])
    arguments = parser.parse_args()
    asyncio.run(run(arguments.providers))


if __name__ == "__main__":
    main()
