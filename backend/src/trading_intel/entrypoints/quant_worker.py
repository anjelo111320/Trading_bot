"""Compute indicators and patterns whenever a candle closes.

Delivery is at-least-once, and every write is idempotent, so a repeat changes nothing.
"""

import argparse
import asyncio
import signal
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Final

import structlog
from anthropic import AsyncAnthropic
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from trading_intel.ai_analyst.exit_review import ClaudeExitReviewer
from trading_intel.ai_analyst.exit_service import ExitReviewService
from trading_intel.core.clock import Clock, SystemClock
from trading_intel.core.errors import ConfigurationError
from trading_intel.core.logging import configure_logging
from trading_intel.core.settings import load_settings
from trading_intel.database.engine import create_engine
from trading_intel.database.repositories.analysis import AnalysisRepository
from trading_intel.database.repositories.candles import CandleRepository
from trading_intel.database.repositories.exchange import ExchangeRepository
from trading_intel.database.repositories.exit_reviews import ExitReviewRepository
from trading_intel.database.repositories.news import NewsRepository
from trading_intel.database.repositories.operations import (
    GapRepository,
    MarketRepository,
    RuleRepository,
    SnapshotRepository,
)
from trading_intel.database.repositories.paper import PaperRepository
from trading_intel.database.repositories.reference import ReferenceRepository
from trading_intel.database.repositories.signals import (
    DEMO_ACCOUNT,
    DEMO_BALANCE,
    EXCHANGE_DEMO_ACCOUNT,
    EXCHANGE_DEMO_BUDGET,
    EXCHANGE_DEMO_MODE,
    PORTFOLIO_ACCOUNT,
    PORTFOLIO_BALANCE,
    Account,
    SignalRepository,
)
from trading_intel.domain.candles import Timeframe
from trading_intel.domain.events import EventEnvelope, MarketCandlePayload
from trading_intel.domain.instruments import Instrument
from trading_intel.events.redis_transport import ClosedCandleConsumer
from trading_intel.execution.binance_futures import (
    BinanceError,
    BinanceFuturesGateway,
    signer_for,
)
from trading_intel.execution.trader import Budget, FuturesTrader, describe
from trading_intel.paper_trading.service import PaperService
from trading_intel.pattern_detection.pipeline import detect_patterns
from trading_intel.technical_analysis.pipeline import (
    FEATURE_SET_VERSION,
    compute_indicators,
    values_at,
)
from trading_intel.technical_analysis.series import CandleSeries
from trading_intel.trade_signals.portfolio import EXCHANGE_DEMO_PROFILE, PLAN_PROFILE
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
    Timeframe.M15: timedelta(minutes=5),
    Timeframe.H1: timedelta(minutes=15),
    Timeframe.D1: timedelta(hours=1),
}
LOOKBACK_CANDLES: Final = 600
MINIMUM_CANDLES: Final = 30
# The signal score reads Bitcoin's trend for every other coin (docs/34).
BITCOIN: Final = "BTCUSDT"


@dataclass(frozen=True)
class ExchangeLink:
    """Binance demo trading, present only when its keys are set (D048)."""

    trader: FuturesTrader
    orders: ExchangeRepository


class TradingLoop:
    """Paper fills on every minute, the pattern strategy at each 1H close, and the daily trend
    strategy at each daily close, after tightening its open stops (D008: perpetuals only).

    The demo bot runs the untested 15M rule baseline at each 15M close, in its own 100 USDT
    account, entering at the live price (D044). The tested strategies' account is untouched.

    The money plan runs once per 15M close for every coin together, in its own 1,000 USDT
    account, with each strategy that closes then (D045).

    With Binance demo keys, the same plan also trades Binance demo futures, once a minute
    every Binance position is checked for its stop, and at each daily close a daily trend
    position there trails its stop (D048).

    At each 15M close, Claude's exit advice on the coin's open paper trades is recorded, in
    shadow mode only, and finished trades' advice is scored (D051).
    """

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
        exchange: ExchangeLink | None = None,
        exits: ExitReviewService | None = None,
    ) -> None:
        self._clock = clock
        self._exchange = exchange
        self._exits = exits
        self._scored: datetime | None = None
        self._checked: datetime | None = None
        self._sleep = sleep
        self._signals = signals
        self._paper = paper
        self._accounts = accounts
        self._owner_email = owner_email
        self._provider_id = provider_id
        self._instruments = instruments
        self._planned: set[datetime] = set()

    async def on_closed(
        self, provider_id: int, instrument_id: int, timeframe: Timeframe, close_time: datetime
    ) -> None:
        instrument = self._instruments.get(instrument_id)
        if provider_id != self._provider_id or instrument is None:
            return
        if timeframe is Timeframe.M1:
            await self._paper.sync(provider_id, instrument_id)
            await self._check_exchange(close_time)
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
        demo = timeframe is Timeframe.M15
        account = await (
            self._accounts.ensure_account(self._owner_email, DEMO_ACCOUNT, DEMO_BALANCE)
            if demo
            else self._accounts.ensure_account(self._owner_email)
        )
        if account is None:
            return
        if demo:
            moved = 0
            outcome = await self._signals.evaluate(
                provider_id, instrument, close_time, account, instant=True
            )
            strategy = "trend_break_baseline"
        elif timeframe is Timeframe.D1:
            moved = await self._signals.trail_stops(provider_id, instrument, close_time)
            await self._trail_exchange(provider_id, instrument, close_time)
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
        if demo:
            try:
                await self._plan(provider_id, close_time)
            except Exception as error:
                # Logged apart from this coin's own signal, which has already been stored.
                log.error(
                    "plan_failed",
                    close_time=close_time.isoformat(),
                    error=type(error).__name__,
                    detail=str(error)[:300],
                )
            await self._review_exits(provider_id, instrument, close_time)

    async def _review_exits(
        self, provider_id: int, instrument: Instrument, close_time: datetime
    ) -> None:
        """Claude's shadow advice on the coin's open paper trades. It changes no trade."""
        if self._exits is None:
            return
        try:
            await self._exits.review(provider_id, instrument, close_time)
            if self._scored != close_time:
                self._scored = close_time  # Once per close, for every coin's finished trades.
                await self._exits.score_finished()
        except Exception as error:
            log.error(
                "exit_review_failed",
                instrument=instrument.symbol,
                error=type(error).__name__,
                detail=str(error)[:300],
            )

    async def _check_exchange(self, close_time: datetime) -> None:
        """Once a minute: no Binance position without its stop, and no order without a position.

        Then the account is saved for the dashboard, which never holds the exchange keys.
        """
        if self._exchange is None or self._checked == close_time:
            return
        self._checked = close_time
        account = await self._exchange_account()
        if account is None:
            return
        try:
            stops = await self._exchange.orders.stops(account.id)
            for record in await self._exchange.trader.reconcile(stops):
                await self._exchange.orders.record(account.id, None, record)
            await self._save_exchange_status(account)
        except Exception as error:
            log.error("exchange_check_failed", error=type(error).__name__, detail=str(error)[:300])

    async def _trail_exchange(
        self, provider_id: int, instrument: Instrument, close_time: datetime
    ) -> None:
        """A daily trend position on Binance trails its stop at the daily close, as on paper."""
        if self._exchange is None:
            return
        account = await self._exchange_account()
        if account is None:
            return
        try:
            await self._signals.trail_exchange_stop(
                provider_id, instrument, close_time, account,
                self._exchange.trader, self._exchange.orders,
            )  # fmt: skip
        except Exception as error:
            # Paper trailing and the day's signals go on. The stop Binance holds still stands.
            log.error(
                "exchange_trail_failed",
                instrument=instrument.symbol,
                error=type(error).__name__,
                detail=str(error)[:300],
            )

    async def _save_exchange_status(self, account: Account) -> None:
        assert self._exchange is not None
        trader, orders = self._exchange.trader, self._exchange.orders
        view = await trader.view()
        today = Timeframe.D1.floor(self._clock.now()).date()
        day_start = await orders.day_start(account.id, today, view.equity)
        baseline = await orders.baseline(account.id) or day_start
        budget = Budget.of(view, account.starting_balance, baseline, day_start)
        body = describe(view, await trader.open_orders(), budget, account.starting_balance)
        await orders.save_status(account.id, self._clock.now(), body)

    async def _exchange_account(self) -> Account | None:
        return await self._accounts.ensure_account(
            self._owner_email, EXCHANGE_DEMO_ACCOUNT, EXCHANGE_DEMO_BUDGET, EXCHANGE_DEMO_PROFILE,
            mode=EXCHANGE_DEMO_MODE,
        )  # fmt: skip

    async def _plan(self, provider_id: int, close_time: datetime) -> None:
        """The money plan, once per close for all coins, so their signals share the room."""
        if close_time in self._planned:
            return
        recent = {at for at in self._planned if close_time - at < timedelta(days=1)}
        self._planned = recent | {close_time}
        account = await self._accounts.ensure_account(
            self._owner_email, PORTFOLIO_ACCOUNT, PORTFOLIO_BALANCE, PLAN_PROFILE
        )
        if account is None or await self._accounts.decided(account.id, close_time):
            # Already decided before a restart: a repeat would store every signal twice.
            return
        setups, missing = await self._signals.plan_setups(
            provider_id, list(self._instruments.values()), close_time
        )
        outcomes = await self._signals.run_plan(provider_id, close_time, account, setups)
        log.info(
            "plan_evaluated",
            close_time=close_time.isoformat(),
            decided=len(setups),
            signals=sum(outcome.recommendation_id is not None for outcome in outcomes),
            approved=sum(outcome.approved for outcome in outcomes),
            missing=missing,
        )
        if self._exchange is None:
            return
        exchange = await self._exchange_account()
        if exchange is None or await self._accounts.decided(exchange.id, close_time):
            return
        try:
            sent = await self._signals.run_exchange_plan(
                provider_id, close_time, exchange, setups,
                self._exchange.trader, self._exchange.orders,
            )  # fmt: skip
        except Exception as error:
            # The paper plan above is already stored; the Binance side fails on its own.
            log.error("exchange_plan_failed", error=type(error).__name__, detail=str(error)[:300])
            return
        log.info(
            "exchange_plan_evaluated",
            close_time=close_time.isoformat(),
            signals=sum(outcome.recommendation_id is not None for outcome in sent),
            approved=sum(outcome.approved for outcome in sent),
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


async def exchange_link(
    engine: AsyncEngine, key: str, secret: str, key_file: Path
) -> ExchangeLink | None:
    """Binance demo trading, if its keys work and the account can use one-way mode."""
    if not key:
        return None
    try:
        signer = signer_for(secret, key_file)
    except ConfigurationError as error:
        log.error("exchange_disabled", detail=error.message)
        return None
    gateway = BinanceFuturesGateway(key, signer)
    try:
        if not await gateway.one_way_mode():
            await gateway.use_one_way_mode()
    except BinanceError as error:
        log.error("exchange_disabled", detail=error.message[:300])
        await gateway.aclose()
        return None
    log.info("exchange_enabled", host="demo-fapi.binance.com")
    return ExchangeLink(FuturesTrader(gateway), ExchangeRepository(engine))


async def build_service(
    engine: AsyncEngine,
    owner_email: str,
    exchange: ExchangeLink | None = None,
    anthropic_key: str = "",
) -> QuantService:
    reference = ReferenceRepository(engine)
    provider_ids = {
        code: await reference.provider_id(code) for code in ("binance_spot", "binance_usdm")
    }
    clock = SystemClock()
    candles = CandleRepository(engine)
    market = MarketRepository(engine)
    paper = PaperRepository(engine)
    accounts = SignalRepository(engine)
    listed = await reference.provider_instruments("binance_usdm")
    signals = SignalService(
        candles,
        SnapshotRepository(engine),
        market,
        GapRepository(engine),
        RuleRepository(engine),
        accounts,
        paper,
        clock,
        bitcoin=next((i.instrument for i in listed if i.instrument.symbol == BITCOIN), None),
    )
    # Without a key, checks are still recorded as not asked, which counts them for free.
    reviewer = ClaudeExitReviewer(AsyncAnthropic(api_key=anthropic_key)) if anthropic_key else None
    exits = ExitReviewService(
        candles, market, paper, ExitReviewRepository(engine), NewsRepository(engine), clock,
        reviewer,
    )  # fmt: skip
    log.info("exit_reviews_enabled", asking=reviewer is not None)
    trading = TradingLoop(
        signals,
        PaperService(candles, market, paper, clock),
        accounts,
        owner_email,
        provider_ids["binance_usdm"],
        {item.instrument.id: item.instrument for item in listed},
        clock,
        exchange=exchange,
        exits=exits,
    )
    return QuantService(candles, AnalysisRepository(engine), provider_ids, trading)


async def run() -> None:
    settings = load_settings()
    configure_logging(settings.log_level, settings.secret_values())
    engine = create_engine(settings.database_url)
    redis: Redis = Redis.from_url(settings.redis_url.get_secret_value())
    link = await exchange_link(
        engine,
        settings.binance_demo_api_key.get_secret_value(),
        settings.binance_demo_api_secret.get_secret_value(),
        settings.binance_demo_private_key_file,
    )
    service = await build_service(
        engine, settings.owner_email, link, settings.anthropic_api_key.get_secret_value()
    )
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
