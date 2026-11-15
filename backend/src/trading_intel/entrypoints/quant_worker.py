"""Compute indicators and patterns whenever a candle closes.

Delivery is at-least-once, and every write is idempotent, so a repeat changes nothing.
"""

import argparse
import asyncio
import contextlib
import signal
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
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
from trading_intel.database.repositories.exchange import CloseRequest, ExchangeRepository
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
    PORTFOLIO_ACCOUNT,
    PORTFOLIO_BALANCE,
    Account,
    SignalRepository,
)
from trading_intel.domain.candles import Timeframe
from trading_intel.domain.events import EventEnvelope, MarketCandlePayload, MarketPricePayload
from trading_intel.domain.instruments import Instrument
from trading_intel.events.redis_transport import ClosedCandleConsumer, RedisEventBus
from trading_intel.execution.binance_futures import (
    BinanceError,
    BinanceFuturesGateway,
    signer_for,
)
from trading_intel.execution.key_check import AccountCheck, KeyChecker, check_account
from trading_intel.execution.trader import Budget, ExchangeView, FuturesTrader, describe
from trading_intel.market_data.ingest import topic_price
from trading_intel.news_intelligence.reading import NewsSignal
from trading_intel.paper_trading.service import PaperService
from trading_intel.pattern_detection.pipeline import detect_patterns
from trading_intel.technical_analysis.pipeline import (
    FEATURE_SET_VERSION,
    compute_indicators,
    values_at,
)
from trading_intel.technical_analysis.series import CandleSeries
from trading_intel.trade_signals.exchange_accounts import DEMO, LIVE, ExchangeKind
from trading_intel.trade_signals.portfolio import PLAN_PROFILE
from trading_intel.trade_signals.service import Setup, SignalService

log = structlog.get_logger(__name__)

GROUP: Final = "quant"
# Strategies act only on fresh closes. After sleep, or a backlog in the stream, older closes
# are skipped: trading them late would act on a market that has moved. Paper fills still
# replay every minute, which is safe because each fill is recorded once.
# A close is decided this long after it, so the ingestor has written the minute's order book
# and the other timeframes' candles. Without it, a decision could read a book a minute old.
SETTLE: Final = timedelta(seconds=10)
# How often Binance demo's fills and funding are copied for the Bot page's results (D057).
HISTORY_EVERY: Final = timedelta(minutes=5)
# Fills are read from a minute before the bot's first entry on a coin.
HISTORY_MARGIN: Final = timedelta(minutes=1)
# How often the owner's closes from the dashboard are looked for, and the real account's key
# and settings checked with Binance (D060).
CLOSE_POLL: Final = timedelta(seconds=2)
LIVE_CHECK_EVERY: Final = timedelta(hours=1)
LIVE_RECHECK: Final = timedelta(minutes=5)
FRESH: Final[dict[Timeframe, timedelta]] = {
    Timeframe.M15: timedelta(minutes=5),
    Timeframe.H1: timedelta(minutes=15),
    Timeframe.D1: timedelta(hours=1),
}
LOOKBACK_CANDLES: Final = 600
MINIMUM_CANDLES: Final = 30
# The signal score reads Bitcoin's trend for every other coin (docs/34).
BITCOIN: Final = "BTCUSDT"


@dataclass
class ExchangeLink:
    """A Binance account the bot trades, present only when its keys are set: demo trading's
    test funds (D048), or the owner's real futures wallet (D060).

    One lock per account keeps the minute check, the plan, the daily trail and the owner's
    closes from sending orders for it at the same time. The real account's key and settings
    are checked with Binance hourly, and any problem stops its new trades.
    """

    kind: ExchangeKind
    trader: FuturesTrader
    orders: ExchangeRepository
    check: Callable[[], Awaitable[AccountCheck]] | None = None
    health: AccountCheck | None = None
    checked_at: datetime | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Coins of open trades seen flat at the last minute check. A trade ends only when its coin
    # is flat twice in a row, so one odd reply from Binance never hands a position to the owner.
    flat_once: set[str] = field(default_factory=set)


class NewsReadings:
    """Each coin's news reading at every 4H close, with the close price, so the news signal
    can be tested forward (D055, docs/39). Stored only: no trade reads it."""

    def __init__(self, candles: CandleRepository, news: NewsRepository, signal: NewsSignal) -> None:
        self._candles = candles
        self._news = news
        self._signal = signal

    async def record(self, provider_id: int, instrument: Instrument, close_time: datetime) -> None:
        if Timeframe.H4.close_time(Timeframe.H4.floor(close_time)) != close_time:
            return
        opened = Timeframe.M15.floor(close_time)
        closing = await self._candles.range(
            provider_id, instrument.id, Timeframe.M15, opened, opened + Timeframe.M15.delta
        )
        if not closing:
            log.warning("news_reading_skipped", instrument=instrument.symbol, reason="no candle")
            return
        reading = await self._signal.reading(instrument.id, close_time)
        stored = await self._news.record_reading(
            instrument.id, close_time, closing[-1].close, reading
        )
        log.info(
            "news_reading_recorded",
            instrument=instrument.symbol,
            direction=reading.direction,
            score=str(reading.score),
            stories=len(reading.stories),
            stored=stored,
        )


class TradingLoop:
    """Paper fills on every minute, the pattern strategy at each 1H close, and the daily trend
    strategy at each daily close, after tightening its open stops (D008: perpetuals only).

    The demo bot runs the untested 15M rule baseline at each 15M close, in its own 100 USDT
    account, entering at the live price (D044). The tested strategies' account is untouched.

    The money plan runs once per 15M close for every coin together, in its own 1,000 USDT
    account, with each strategy that closes then (D045).

    With Binance keys, the same plan also trades Binance futures: demo trading's test funds
    (D048) and, once the owner arms it, their real futures wallet (D060). Once a minute every
    Binance position is checked for its stop, each trade that ended is recorded, and at each
    daily close a daily trend position there trails its stop. The owner's closes from the
    dashboard are carried out within seconds (`run_closes`).

    At each 15M close, Claude's exit advice on the coin's open paper trades is recorded, in
    shadow mode only, and finished trades' advice is scored (D051).

    At each 4H close, each coin's news reading is stored to test the news signal (D055).
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
        exchanges: Sequence[ExchangeLink] = (),
        exits: ExitReviewService | None = None,
        news: NewsReadings | None = None,
    ) -> None:
        self._clock = clock
        self._news = news
        self._exchanges = tuple(exchanges)
        self._exits = exits
        self._scored: datetime | None = None
        # Per Binance account, by name: its last minute check, its last history copy, and the
        # account as the minute check last read it.
        self._checked: dict[str, datetime] = {}
        self._history_at: dict[str, datetime] = {}
        self._known: dict[str, Account] = {}
        self._sleep = sleep
        self._signals = signals
        self._paper = paper
        self._accounts = accounts
        self._owner_email = owner_email
        self._provider_id = provider_id
        self._instruments = instruments
        self._by_symbol = {instrument.symbol: instrument for instrument in instruments.values()}
        self._planned: set[datetime] = set()

    async def on_closed(
        self, provider_id: int, instrument_id: int, timeframe: Timeframe, close_time: datetime
    ) -> None:
        instrument = self._instruments.get(instrument_id)
        if provider_id != self._provider_id or instrument is None:
            return
        if timeframe is Timeframe.M1:
            await self._paper.sync(provider_id, instrument_id)
            for link in self._exchanges:
                await self._check_exchange(link, close_time)
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
            await self._record_news(provider_id, instrument, close_time)

    async def _record_news(
        self, provider_id: int, instrument: Instrument, close_time: datetime
    ) -> None:
        if self._news is None:
            return
        try:
            await self._news.record(provider_id, instrument, close_time)
        except Exception as error:
            log.error(
                "news_reading_failed",
                instrument=instrument.symbol,
                error=type(error).__name__,
                detail=str(error)[:300],
            )

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

    async def _check_exchange(self, link: ExchangeLink, close_time: datetime) -> None:
        """Once a minute: no Binance position without its stop, and no order without a position.

        Then each trade the bot sees has ended is recorded, whether a stop or target filled or
        the owner closed it in the Binance app, so its margin is free for the next trade at
        once. The real account's transfers are copied, and the account is saved for the
        dashboard, which never holds the exchange keys.
        """
        name = link.kind.name
        if self._checked.get(name) == close_time:
            return
        self._checked[name] = close_time
        async with link.lock:
            ended = False
            try:
                # Inside the guard: making the real account reads Binance, and a failure there
                # must not stop the worker for every other account.
                account = await self._exchange_account(link, create=True)
                if account is None:
                    return
                await self._health(link)
                stops = await (
                    link.orders.open_trades(account.id)
                    if link.kind.live
                    else link.orders.stops(account.id)
                )
                for record in await link.trader.reconcile(stops):
                    await link.orders.record(account.id, None, record)
                await self._lock_profits(link, account)
                view = await link.trader.view()
                ended = await self._record_ends(link, account, view)
                if link.kind.live:
                    await self._copy_transfers(link, account)
                await self._save_exchange_status(link, account, view)
            except Exception as error:
                log.error(
                    "exchange_check_failed",
                    account=name,
                    error=type(error).__name__,
                    detail=str(error)[:300],
                )
                return
            last = self._history_at.get(name)
            if ended or last is None or close_time - last >= HISTORY_EVERY:
                self._history_at[name] = close_time
                try:
                    await self._copy_history(link, account)
                except Exception as error:
                    log.error(
                        "exchange_history_failed",
                        account=name,
                        error=type(error).__name__,
                        detail=str(error)[:300],
                    )

    async def _lock_profits(self, link: ExchangeLink, account: Account) -> None:
        """The profit lock (D066). A failure leaves every stop as Binance holds it, and the rest
        of the minute check goes on."""
        try:
            await self._signals.lock_exchange_profits(
                self._provider_id, account, link.trader, link.orders, self._by_symbol,
                live=link.kind.live,
            )  # fmt: skip
        except Exception as error:
            log.error(
                "exchange_profit_lock_failed",
                account=link.kind.name,
                error=type(error).__name__,
                detail=str(error)[:300],
            )

    async def _health(self, link: ExchangeLink) -> None:
        """The real account's key and settings, asked of Binance hourly (D060), and every few
        minutes while a problem stands, so a fix on Binance is seen soon."""
        now = self._clock.now()
        every = (
            LIVE_RECHECK if link.health is not None and link.health.problems else LIVE_CHECK_EVERY
        )
        if link.check is None or (link.checked_at is not None and now - link.checked_at < every):
            return
        link.health, link.checked_at = await link.check(), now
        if link.health.problems:
            log.error("exchange_live_refused", problems=list(link.health.problems))

    async def _record_ends(self, link: ExchangeLink, account: Account, view: ExchangeView) -> bool:
        """Record each open trade of the bot's whose coin is flat on Binance, with no waiting
        entry of the bot's left, at two minute checks in a row. Returns whether any ended, so
        its fills are copied at once.

        One check is not enough on the real account: an ended trade's coin belongs to the
        owner, so a single empty reply from Binance would leave the bot's position to the
        owner and cancel its stop. Two in a row cost a minute; meanwhile the stop is restored.
        """
        waiting = {s for s, e in view.pending.items() if not link.trader.own_only or e.by_bot}
        ended = False
        flat_now: set[str] = set()
        for symbol, (_, key) in sorted((await link.orders.open_trades(account.id)).items()):
            if symbol in view.positions or symbol in waiting:
                continue
            flat_now.add(symbol)
            if symbol not in link.flat_once:
                continue
            if await link.orders.end_trade(account.id, key, symbol, "flat_on_binance"):
                log.info("exchange_trade_ended", account=link.kind.name, instrument=symbol)
                ended = True
        link.flat_once = flat_now
        return ended

    async def _copy_transfers(self, link: ExchangeLink, account: Account) -> None:
        """USDT the owner moved into or out of the real futures wallet, so the bot never takes a
        transfer for a profit or a loss (D060). Read from the futures wallet's own income."""
        since = await link.orders.last_transfer_at(account.id)
        start = since or await link.orders.first_seen(account.id)
        if start is None:
            return
        now_ms = int(self._clock.now().timestamp() * 1000)
        rows = await link.trader.transfers(int(start.timestamp() * 1000) + 1, now_ms)
        stored = await link.orders.store_transfers(account.id, rows)
        if stored:
            log.info("exchange_transfers_copied", account=link.kind.name, transfers=stored)

    async def _copy_history(self, link: ExchangeLink, account: Account) -> None:
        """Binance's own fills and funding for every coin the bot traded, kept here because
        Binance keeps them only 3 months. The Bot page's results are rebuilt from them."""
        trader, orders = link.trader, link.orders
        now_ms = int(self._clock.now().timestamp() * 1000)
        traded = await orders.traded_symbols(account.id)
        if not traded:
            return
        last = await orders.last_fill_ids(account.id)
        fills = 0
        for symbol, first in sorted(traded.items()):
            start_ms = int((first - HISTORY_MARGIN).timestamp() * 1000)
            rows = await trader.fills(symbol, last.get(symbol), start_ms, now_ms)
            fills += await orders.store_fills(account.id, rows)
        since = await orders.last_funding_at(account.id) or min(traded.values()) - HISTORY_MARGIN
        rows = await trader.funding(int(since.timestamp() * 1000) + 1, now_ms)
        funding = await orders.store_funding(account.id, rows)
        if fills or funding:
            log.info(
                "exchange_history_copied", account=link.kind.name, fills=fills, funding=funding
            )

    async def _trail_exchange(
        self, provider_id: int, instrument: Instrument, close_time: datetime
    ) -> None:
        """A daily trend position on Binance trails its stop at the daily close, as on paper."""
        for link in self._exchanges:
            async with link.lock:
                account = await self._exchange_account(link)
                if account is None:
                    continue
                try:
                    await self._signals.trail_exchange_stop(
                        provider_id, instrument, close_time, account, link.trader, link.orders,
                        live=link.kind.live,
                    )  # fmt: skip
                except Exception as error:
                    # Paper trailing and the day's signals go on. Binance's stop still stands.
                    log.error(
                        "exchange_trail_failed",
                        account=link.kind.name,
                        instrument=instrument.symbol,
                        error=type(error).__name__,
                        detail=str(error)[:300],
                    )

    async def _save_exchange_status(
        self, link: ExchangeLink, account: Account, view: ExchangeView
    ) -> None:
        """The account as the dashboard shows it. On the real account the whole futures wallet
        is the bot's, the owner's own positions and orders are marked, and the snapshot says
        whether the account is armed and what the hourly check found (D060)."""
        trader, orders = link.trader, link.orders
        today = Timeframe.D1.floor(self._clock.now()).date()
        # An empty wallet records no day: a day's starting equity must be above zero.
        day_start = (
            await orders.day_start(account.id, today, view.equity)
            if view.equity > 0
            else Decimal(0)
        )
        if link.kind.live:
            moved = await orders.moved_today(account.id, today)
            budget = Budget.wallet(view, day_start, moved)
            capital = await orders.funded(account.id) or account.starting_balance
            trades: set[str] | None = set(await orders.open_trades(account.id))
        else:
            baseline = await orders.baseline(account.id) or day_start
            budget = Budget.of(view, account.starting_balance, baseline, day_start)
            capital, trades = account.starting_balance, None
        body = describe(view, await trader.open_orders(), budget, capital, trades)
        if link.kind.live:
            armed, armed_at, armed_by = await orders.arming(account.id)
            health = link.health
            body["live"] = {
                "armed": armed,
                "armed_at": None if armed_at is None else armed_at.isoformat(),
                "armed_by": armed_by,
                "checked_at": None if link.checked_at is None else link.checked_at.isoformat(),
                "problems": (
                    ["not checked with Binance yet"] if health is None else list(health.problems)
                ),
                "ip_restricted": None if health is None else health.ip_restricted,
            }
        await orders.save_status(account.id, self._clock.now(), body)

    async def _exchange_account(self, link: ExchangeLink, create: bool = False) -> Account | None:
        """The bot's account for this Binance link. Demo trading's is made with its budget on
        first use. The real account is made only by the minute check (`create`), from the
        equity it first sees in the futures wallet, since that is what the owner put in."""
        kind = link.kind
        if kind.budget is not None:
            account = await self._accounts.ensure_account(
                self._owner_email, kind.name, kind.budget, kind.profile, mode=kind.mode
            )
        else:
            account = await self._accounts.find_account(self._owner_email, kind.name)
            if account is None and create:
                equity = (await link.trader.view()).equity
                if equity > 0:
                    log.info("exchange_account_created", account=kind.name, equity=str(equity))
                    account = await self._accounts.ensure_account(
                        self._owner_email, kind.name, equity, kind.profile, mode=kind.mode
                    )
        if account is not None:
            self._known[kind.name] = account
        return account

    async def run_closes(self) -> None:
        """The owner's closes from the dashboard, carried out within seconds (D060).

        The API only stores a request, because it never holds a key. Only an open trade of the
        bot's is closed: the owner's own positions stay theirs to close in the Binance app.
        """
        for link in self._exchanges:
            account = self._known.get(link.kind.name)
            if account is None:
                continue
            for request in await link.orders.waiting_closes(account.id):
                async with link.lock:
                    await self._close(link, account, request)

    async def _close(self, link: ExchangeLink, account: Account, request: CloseRequest) -> None:
        orders, name, symbol = link.orders, link.kind.name, request.symbol
        trade = (await orders.open_trades(account.id)).get(symbol)
        if trade is None:
            detail = "the bot has no open trade on this coin"
            await orders.finish_close(request.id, "not_the_bots", detail)
            log.info("exchange_close_done", account=name, instrument=symbol, outcome="not_the_bots")
            return
        try:
            result = await link.trader.close_trade(symbol, f"dashboard:{request.id}")
        except Exception as error:
            detail = f"{type(error).__name__}: {str(error)[:200]}"
            await orders.finish_close(request.id, "failed", detail)
            log.error("exchange_close_failed", account=name, instrument=symbol, detail=detail)
            return
        for record in result.records:
            await orders.record(account.id, None, record)
        if result.outcome != "failed":
            await orders.end_trade(account.id, trade[1], symbol, "closed_from_dashboard")
        await orders.finish_close(request.id, result.outcome, result.detail)
        log.info("exchange_close_done", account=name, instrument=symbol, outcome=result.outcome)
        # The dashboard and the results show it at once, not at the next minute check.
        try:
            await self._save_exchange_status(link, account, await link.trader.view())
            await self._copy_history(link, account)
        except Exception as error:
            log.error("exchange_check_failed", account=name, error=type(error).__name__)

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
        for link in self._exchanges:
            async with link.lock:
                await self._plan_exchange(link, provider_id, close_time, setups)

    async def _plan_exchange(
        self, link: ExchangeLink, provider_id: int, close_time: datetime, setups: list[Setup]
    ) -> None:
        """The same setups on one Binance account, while its switch is on (D064). The real
        account trades only once the owner has armed it and its hourly check found no problem
        (D060)."""
        name = link.kind.name
        exchange = await self._exchange_account(link)
        if exchange is None or await self._accounts.decided(exchange.id, close_time):
            return
        blocked = await self._blocked(link, exchange)
        if blocked is not None:
            log.info("exchange_plan_skipped", account=name, reason=blocked)
            return
        try:
            if link.kind.live:
                await self._copy_transfers(link, exchange)  # A transfer just made is no result.
            sent = await self._signals.run_exchange_plan(
                provider_id, close_time, exchange, setups, link.trader, link.orders,
                live=link.kind.live,
            )  # fmt: skip
        except Exception as error:
            # The paper plan above is already stored; each Binance account fails on its own.
            log.error(
                "exchange_plan_failed",
                account=name,
                error=type(error).__name__,
                detail=str(error)[:300],
            )
            return
        log.info(
            "exchange_plan_evaluated",
            account=name,
            close_time=close_time.isoformat(),
            signals=sum(outcome.recommendation_id is not None for outcome in sent),
            approved=sum(outcome.approved for outcome in sent),
        )

    async def _blocked(self, link: ExchangeLink, account: Account) -> str | None:
        """Why the account may not open a trade now, or None when it may. Open trades keep
        their stops and targets either way, and closes from the dashboard still run."""
        armed, _, _ = await link.orders.arming(account.id, default=link.kind.starts_on)
        if not armed and not link.kind.live:
            return "switched off on the Bot page"
        if not armed:
            return "not armed: turn real trading on with the Bot page switch or binance_live arm"
        if not link.kind.live:
            return None
        if link.health is None:
            return "the key and account are not checked with Binance yet"
        if link.health.problems:
            return "; ".join(link.health.problems)
        return None


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

    async def run_closes(self) -> None:
        if self._trading is not None:
            await self._trading.run_closes()


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
    return ExchangeLink(DEMO, FuturesTrader(gateway), ExchangeRepository(engine))


async def live_link(
    engine: AsyncEngine, key: str, secret: str, key_file: Path
) -> ExchangeLink | None:
    """The owner's real futures wallet (D060), when its key is set.

    The bot reads and trades futures only, and only its own orders and trades. It opens no
    trade until the owner arms the account and the hourly check finds a key that can neither
    withdraw nor transfer, one-way mode and USDT-only margin. The account's settings are never
    changed for the owner.
    """
    if not key:
        return None
    try:
        signer = signer_for(secret, key_file)
    except ConfigurationError as error:
        log.error("exchange_disabled", account=LIVE.name, detail=error.message)
        return None
    gateway = BinanceFuturesGateway(key, signer, venue="live")
    keys = KeyChecker(key, signer, now_ms=gateway.server_ms)

    async def check() -> AccountCheck:
        return await check_account(gateway, keys)

    link = ExchangeLink(
        LIVE, FuturesTrader(gateway, own_only=True), ExchangeRepository(engine), check
    )
    log.info("exchange_enabled", host="fapi.binance.com", account=LIVE.name)
    return link


class RedisQuotes:
    """The live quotes the ingestor publishes to Redis for each perpetual, a few times a
    second, kept there for a minute (D071)."""

    def __init__(self, bus: RedisEventBus, provider: str) -> None:
        self._bus = bus
        self._provider = provider

    async def quote(self, instrument_id: int) -> tuple[datetime, Decimal, Decimal] | None:
        envelope = await self._bus.latest(topic_price(self._provider, instrument_id))
        if envelope is None:
            return None
        price = MarketPricePayload.model_validate(envelope.payload)
        return price.received_at, Decimal(price.bid), Decimal(price.ask)


async def build_service(
    engine: AsyncEngine,
    owner_email: str,
    exchanges: Sequence[ExchangeLink] = (),
    anthropic_key: str = "",
    quotes: RedisQuotes | None = None,
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
    news = NewsRepository(engine)
    news_signal = NewsSignal(news)
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
        news=news_signal,
        quotes=quotes,
    )
    # Without a key, checks are still recorded as not asked, which counts them for free.
    reviewer = ClaudeExitReviewer(AsyncAnthropic(api_key=anthropic_key)) if anthropic_key else None
    exits = ExitReviewService(
        candles, market, paper, ExitReviewRepository(engine), news, clock, reviewer,
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
        exchanges=exchanges,
        exits=exits,
        news=NewsReadings(candles, news, news_signal),
    )
    return QuantService(candles, AnalysisRepository(engine), provider_ids, trading)


async def closes_until(service: QuantService, stop: asyncio.Event) -> None:
    """Carry out the owner's closes from the dashboard every couple of seconds, until stopped."""
    while not stop.is_set():
        try:
            await service.run_closes()
        except Exception as error:
            log.error("exchange_close_failed", error=type(error).__name__, detail=str(error)[:300])
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), CLOSE_POLL.total_seconds())


async def run() -> None:
    settings = load_settings()
    configure_logging(settings.log_level, settings.secret_values())
    engine = create_engine(settings.database_url)
    redis: Redis = Redis.from_url(settings.redis_url.get_secret_value())
    demo = await exchange_link(
        engine,
        settings.binance_demo_api_key.get_secret_value(),
        settings.binance_demo_api_secret.get_secret_value(),
        settings.binance_demo_private_key_file,
    )
    live = await live_link(
        engine,
        settings.binance_live_api_key.get_secret_value(),
        settings.binance_live_api_secret.get_secret_value(),
        settings.binance_live_private_key_file,
    )
    links = [link for link in (demo, live) if link is not None]
    quotes = RedisQuotes(RedisEventBus(redis, SystemClock()), "binance_usdm")
    service = await build_service(
        engine, settings.owner_email, links, settings.anthropic_api_key.get_secret_value(), quotes
    )
    consumer = ClosedCandleConsumer(redis, GROUP, "worker-1")
    await consumer.ensure_group()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for number in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(number, stop.set)
    closes = asyncio.create_task(closes_until(service, stop))
    log.info("quant_worker_started", exchanges=[link.kind.name for link in links])
    while not stop.is_set():
        try:
            await consumer.process_once(service.handle)
        except (ConnectionError, OSError) as error:
            log.warning("quant_worker_retry", error=type(error).__name__)
            await asyncio.sleep(2)
    await closes
    await redis.aclose()
    await engine.dispose()


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    asyncio.run(run())


if __name__ == "__main__":
    main()
