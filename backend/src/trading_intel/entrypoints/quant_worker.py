"""Compute indicators and patterns whenever a candle closes.

Delivery is at-least-once, and every write is idempotent, so a repeat changes nothing.
"""

import argparse
import asyncio
import signal
from datetime import datetime
from typing import Final

import structlog
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from trading_intel.core.logging import configure_logging
from trading_intel.core.settings import load_settings
from trading_intel.database.engine import create_engine
from trading_intel.database.repositories.analysis import AnalysisRepository
from trading_intel.database.repositories.candles import CandleRepository
from trading_intel.database.repositories.reference import ReferenceRepository
from trading_intel.domain.candles import Timeframe
from trading_intel.domain.events import EventEnvelope, MarketCandlePayload
from trading_intel.events.redis_transport import ClosedCandleConsumer
from trading_intel.pattern_detection.pipeline import detect_patterns
from trading_intel.technical_analysis.pipeline import (
    FEATURE_SET_VERSION,
    compute_indicators,
    values_at,
)
from trading_intel.technical_analysis.series import CandleSeries

log = structlog.get_logger(__name__)

GROUP: Final = "quant"
LOOKBACK_CANDLES: Final = 600
MINIMUM_CANDLES: Final = 30


class QuantService:
    def __init__(
        self,
        candles: CandleRepository,
        analysis: AnalysisRepository,
        provider_ids: dict[str, int],
    ) -> None:
        self._candles = candles
        self._analysis = analysis
        self._provider_ids = provider_ids

    async def process(
        self, provider_id: int, instrument_id: int, timeframe: Timeframe, as_of: datetime
    ) -> bool:
        """Compute as of a close time. Reading by close time keeps this free of look-ahead."""
        candles = await self._candles.for_analysis(
            provider_id, instrument_id, timeframe, as_of, LOOKBACK_CANDLES
        )
        if len(candles) < MINIMUM_CANDLES:
            return False
        series = CandleSeries.of(candles)
        await self._analysis.store_indicators(
            provider_id,
            instrument_id,
            timeframe,
            candles[-1].close_time,
            FEATURE_SET_VERSION,
            values_at(compute_indicators(series), -1),
        )
        await self._analysis.store_patterns(
            provider_id, instrument_id, timeframe, detect_patterns(series)
        )
        return True

    async def handle(self, envelope: EventEnvelope) -> None:
        payload = MarketCandlePayload.model_validate(envelope.payload)
        if not payload.is_closed or payload.provider not in self._provider_ids:
            return
        await self.process(
            self._provider_ids[payload.provider],
            payload.instrument_id,
            payload.timeframe,
            payload.close_time,
        )


async def build_service(engine: AsyncEngine) -> QuantService:
    reference = ReferenceRepository(engine)
    provider_ids = {
        code: await reference.provider_id(code) for code in ("binance_spot", "binance_usdm")
    }
    return QuantService(CandleRepository(engine), AnalysisRepository(engine), provider_ids)


async def run() -> None:
    settings = load_settings()
    configure_logging(settings.log_level, settings.secret_values())
    engine = create_engine(settings.database_url)
    redis: Redis = Redis.from_url(settings.redis_url.get_secret_value())
    service = await build_service(engine)
    consumer = ClosedCandleConsumer(redis, GROUP, "worker-1")
    await consumer.ensure_group()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for number in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(number, stop.set)
    log.info("quant_worker_started")
    while not stop.is_set():
        try:
            await consumer.process_once(service.handle)
        except (ConnectionError, OSError) as error:
            log.warning("quant_worker_retry", error=type(error).__name__)
            await asyncio.sleep(2)
    await redis.aclose()
    await engine.dispose()


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    asyncio.run(run())


if __name__ == "__main__":
    main()
