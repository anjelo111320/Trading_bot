"""Compute indicators and patterns whenever a candle closes.

Delivery is at-least-once, and every write is idempotent, so a repeat changes nothing.
"""

import argparse
import asyncio
import signal
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Final

import structlog
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from trading_intel.core.clock import Clock, SystemClock
from trading_intel.core.logging import configure_logging
from trading_intel.core.settings import load_settings
from trading_intel.database.engine import create_engine
from trading_intel.database.repositories.analysis import AnalysisRepository
from trading_intel.database.repositories.candles import CandleRepository
from trading_intel.database.repositories.operations import (
    GapRepository,
    MarketRepository,
    RuleRepository,
    SnapshotRepository,
)
from trading_intel.database.repositories.paper import PaperRepository
from trading_intel.database.repositories.reference import ReferenceRepository
from trading_intel.database.repositories.signals import SignalRepository
from trading_intel.domain.candles import Timeframe
from trading_intel.domain.events import EventEnvelope, MarketCandlePayload
from trading_intel.domain.instruments import Instrument
from trading_intel.events.redis_transport import ClosedCandleConsumer
from trading_intel.paper_trading.service import PaperService
from trading_intel.pattern_detection.pipeline import detect_patterns
from trading_intel.technical_analysis.pipeline import (
    FEATURE_SET_VERSION,
    compute_indicators,
    values_at,
)
from trading_intel.technical_analysis.series import CandleSeries
from trading_intel.trade_signals.service import SignalService

log = structlog.get_logger(__name__)

GROUP: Final = "quant"
# Strategies act only on fresh closes. After sleep, or a backlog in the stream, older closes
# are skipped: trading them late would act on a market that has moved. Paper fills still
# replay every minute, which is safe because each fill is recorded once.
# A close is decided this long after it, so the ingestor has written the minute's order book
# and the other timeframes' candles. Without it, a decision could read a book a minute old.
SETTLE: Final = timedelta(seconds=10)
FRESH: Final[dict[Timeframe, timedelta]] = {
    Timeframe.H1: timedelta(minutes=15),
    Timeframe.D1: timedelta(hours=1),
}
LOOKBACK_CANDLES: Final = 600
MINIMUM_CANDLES: Final = 30


class TradingLoop:
    """Paper fills on every minute, the pattern strategy at each 1H close, and the daily trend
    strategy at each daily close, after tightening its open stops (D008: perpetuals only)."""

    def __init__(
        self,
        signals: SignalService,
        paper: PaperService,
        accounts: SignalRepository,
        owner_email: str,
        provider_id: int,
        instruments: dict[int, Instrument],
        clock: Clock,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._clock = clock
        self._sleep = sleep
        self._signals = signals
        self._paper = paper
        self._accounts = accounts
        self._owner_email = owner_email
        self._provider_id = provider_id
        self._instruments = instruments

    async def on_closed(
        self, provider_id: int, instrument_id: int, timeframe: Timeframe, close_time: datetime
    ) -> None:
        instrument = self._instruments.get(instrument_id)
        if provider_id != self._provider_id or instrument is None:
            return
        if timeframe is Timeframe.M1:
            await self._paper.sync(provider_id, instrument_id)
            return
        try:
            await self._decide(instrument, provider_id, timeframe, close_time)
        except Exception as error:
            # One bad signal must not stop paper trading for every coin. The failure is
            # logged with its cause, and the next close is decided as usual.
            log.error(
                "signal_failed",
                instrument=instrument.symbol,
                timeframe=timeframe.value,
                error=type(error).__name__,
                detail=str(error)[:300],
            )

    async def _decide(
        self, instrument: Instrument, provider_id: int, timeframe: Timeframe, close_time: datetime
    ) -> None:
        fresh = FRESH.get(timeframe)
        if fresh is None:
            return
        if self._clock.now() - close_time > fresh:
            log.info(
                "signal_skipped_stale",
                instrument=instrument.symbol,
                timeframe=timeframe.value,
                close_time=close_time.isoformat(),
            )
            return
        wait = (close_time + SETTLE - self._clock.now()).total_seconds()
        if wait > 0:
            await self._sleep(wait)
        account = await self._accounts.ensure_account(self._owner_email)
        if account is None:
            return
        if timeframe is Timeframe.D1:
            moved = await self._signals.trail_stops(provider_id, instrument, close_time)
            outcome = await self._signals.evaluate_trend(
                provider_id, instrument, close_time, account
            )
            strategy = "daily_trend"
        else:
            moved = 0
            outcome = await self._signals.evaluate_pattern(
                provider_id, instrument, close_time, account
            )
            strategy = "pattern_breakout"
        log.info(
            "signal_evaluated",
            strategy=strategy,
            instrument=instrument.symbol,
            action=outcome.action.value,
            approved=outcome.approved,
            reasons=outcome.reasons,
            stops_moved=moved,
        )


class QuantService:
    def __init__(
        self,
        candles: CandleRepository,
        analysis: AnalysisRepository,
        provider_ids: dict[str, int],
        trading: TradingLoop | None = None,
    ) -> None:
        self._candles = candles
        self._analysis = analysis
        self._provider_ids = provider_ids
        self._trading = trading

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
        provider_id = self._provider_ids[payload.provider]
        await self.process(
            provider_id, payload.instrument_id, payload.timeframe, payload.close_time
        )
        if self._trading is not None:
            await self._trading.on_closed(
                provider_id, payload.instrument_id, payload.timeframe, payload.close_time
            )


async def build_service(engine: AsyncEngine, owner_email: str) -> QuantService:
    reference = ReferenceRepository(engine)
    provider_ids = {
        code: await reference.provider_id(code) for code in ("binance_spot", "binance_usdm")
    }
    clock = SystemClock()
    candles = CandleRepository(engine)
    market = MarketRepository(engine)
    paper = PaperRepository(engine)
    accounts = SignalRepository(engine)
    signals = SignalService(
        candles,
        SnapshotRepository(engine),
        market,
        GapRepository(engine),
        RuleRepository(engine),
        accounts,
        paper,
        clock,
    )
    listed = await reference.provider_instruments("binance_usdm")
    trading = TradingLoop(
        signals,
        PaperService(candles, market, paper, clock),
        accounts,
        owner_email,
        provider_ids["binance_usdm"],
        {item.instrument.id: item.instrument for item in listed},
        clock,
    )
    return QuantService(candles, AnalysisRepository(engine), provider_ids, trading)


async def run() -> None:
    settings = load_settings()
    configure_logging(settings.log_level, settings.secret_values())
    engine = create_engine(settings.database_url)
    redis: Redis = Redis.from_url(settings.redis_url.get_secret_value())
    service = await build_service(engine, settings.owner_email)
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
