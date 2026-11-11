"""Claude's exit advice on open paper trades, in shadow mode (D051, docs/38).

At each 15M close, every open paper trade on the coin is replayed through the shared
simulator to that close, and the docs/37 checks run on it. When one fires, Claude Haiku is
asked, if a key and budget allow, and the answer is stored. When a trade finishes, each
answer is scored by replaying the trade with it applied. No trade ever changes here.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final

import structlog

from trading_intel.ai_analyst.exit_checks import (
    RANGE_WINDOW,
    PriorReview,
    TradeAtClose,
    fired_checks,
    usual_range,
)
from trading_intel.ai_analyst.exit_review import (
    MODEL,
    OUTPUT_SCHEMA_VERSION,
    PROMPT_BODY,
    PROMPT_NAME,
    PROMPT_SHA256,
    PROMPT_VERSION,
    ExitReviewer,
    TradeFacts,
    render_facts,
)
from trading_intel.backtesting.exits import breakeven_stop
from trading_intel.core.clock import Clock
from trading_intel.database.repositories.candles import CandleRepository
from trading_intel.database.repositories.exit_reviews import ExitReviewRepository, NewReview
from trading_intel.database.repositories.news import NewsRepository
from trading_intel.database.repositories.operations import MarketRepository
from trading_intel.database.repositories.paper import OpenTrade, PaperRepository
from trading_intel.domain.candles import ClosedCandle, Timeframe
from trading_intel.domain.instruments import Instrument
from trading_intel.news_intelligence.classifier import cost_usd
from trading_intel.paper_trading.service import build_order
from trading_intel.paper_trading.simulator import OrderStatus, TradeSimulator, summarise

log = structlog.get_logger(__name__)

DAILY_LIMIT_USD: Final = Decimal(3)  # Shared by every Claude call (docs/24).
QUARTERS_SHOWN: Final = 8
HOURS_SHOWN: Final = 6
PURPOSE: Final = "exit_review"
ZERO: Final = Decimal(0)

Funding = Sequence[tuple[datetime, Decimal, Decimal | None]]


@dataclass(frozen=True)
class Replayed:
    """A trade replayed on 1M candles, and its best and worst prices after the entry minute."""

    simulator: TradeSimulator
    best: Decimal | None = None
    best_at: datetime | None = None
    worst: Decimal | None = None


def replay_trade(
    trade: OpenTrade,
    minutes: Sequence[ClosedCandle],
    funding: Funding,
    *,
    until: datetime | None = None,
    advice: tuple[datetime, str] | None = None,
) -> Replayed:
    """As `PaperService` replays a trade, up to `until`, with advice applied after its close.

    Taking the profit exits at the next candle's open, and a breakeven stop counts from the
    next candle, the same timing as every stop move (D039).
    """
    order = build_order(trade)
    simulator = TradeSimulator(order)
    pending, moves = list(funding), list(trade.stop_moves)
    sign = order.side.sign
    best: Decimal | None = None
    worst: Decimal | None = None
    best_at: datetime | None = None
    for candle in minutes:
        if until is not None and candle.close_time > until:
            break
        while moves and moves[0][0] < candle.open_time:
            simulator.move_stop(moves.pop(0)[1])
        if advice is not None and candle.open_time > advice[0]:
            if simulator.status is OrderStatus.OPEN and simulator.entry_fill is not None:
                if advice[1] == "take_profit_now":
                    simulator.request_exit()
                elif advice[1] == "stop_to_breakeven":
                    simulator.move_stop(breakeven_stop(order, simulator.entry_fill))
            advice = None
        while pending and pending[0][0] < candle.close_time:
            at, rate, mark = pending.pop(0)
            simulator.on_funding(at, rate, mark or candle.close)
        was_open = simulator.status is OrderStatus.OPEN
        simulator.on_candle(candle)
        if was_open:
            high, low = (candle.high, candle.low) if sign > 0 else (candle.low, candle.high)
            if best is None or sign * (high - best) > 0:
                best, best_at = high, candle.close_time
            if worst is None or sign * (low - worst) < 0:
                worst = low
        if simulator.is_finished:
            break
    return Replayed(simulator, best, best_at, worst)


def r_of(trade: OpenTrade, replayed: Replayed) -> Decimal:
    """Net R, as every report counts it: net profit over the planned risk."""
    result = summarise(trade.side, replayed.simulator.fills)
    return result.net_pnl / (trade.quantity * abs(trade.entry - trade.stop))


class ExitReviewService:
    def __init__(
        self,
        candles: CandleRepository,
        market: MarketRepository,
        paper: PaperRepository,
        reviews: ExitReviewRepository,
        usage: NewsRepository,
        clock: Clock,
        reviewer: ExitReviewer | None = None,
        daily_limit: Decimal = DAILY_LIMIT_USD,
    ) -> None:
        self._candles = candles
        self._market = market
        self._paper = paper
        self._reviews = reviews
        self._usage = usage
        self._clock = clock
        self._reviewer = reviewer
        self._daily_limit = daily_limit

    async def review(self, provider_id: int, instrument: Instrument, close_time: datetime) -> int:
        """Check every open paper trade on the coin at this 15M close. Returns rows stored."""
        trades = [
            t
            for t in await self._paper.active(provider_id, instrument.id)
            if t.created_at < close_time
        ]
        if not trades:
            return 0
        quarters = await self._candles.for_analysis(
            provider_id, instrument.id, Timeframe.M15, close_time, RANGE_WINDOW + 1
        )
        if not quarters or quarters[-1].close_time != close_time:
            return 0  # This close's candle is not stored yet.
        hours = await self._candles.for_analysis(
            provider_id, instrument.id, Timeframe.H1, close_time, HOURS_SHOWN
        )
        usual = usual_range(quarters)
        names = await self._reviews.account_names()
        stored = 0
        for trade in trades:
            stored += await self._review_trade(
                trade, instrument, close_time, quarters, hours, usual, names.get(trade.account_id)
            )
        return stored

    async def _review_trade(
        self,
        trade: OpenTrade,
        instrument: Instrument,
        close_time: datetime,
        quarters: Sequence[ClosedCandle],
        hours: Sequence[ClosedCandle],
        usual: Decimal | None,
        account: str | None,
    ) -> int:
        start = Timeframe.M1.floor(trade.created_at)
        end = close_time + timedelta(milliseconds=1)
        minutes = await self._candles.range(
            trade.provider_id, trade.instrument_id, Timeframe.M1, start, end
        )
        funding = await self._market.funding_between(
            trade.provider_id, trade.instrument_id, trade.created_at, end
        )
        replayed = replay_trade(trade, minutes, funding, until=close_time)
        simulator = replayed.simulator
        entry = simulator.entry_fill
        if simulator.status is not OrderStatus.OPEN or entry is None:
            return 0
        if replayed.best is None or replayed.best_at is None or replayed.worst is None:
            return 0  # Still in its entry minute.
        risk = abs(trade.entry - trade.stop)
        state = TradeAtClose(
            side=trade.side,
            entry=entry,
            risk=risk,
            targets=trade.targets,
            targets_hit=simulator.next_target,
            tick=simulator.order.tick,
            best=replayed.best,
            best_at=replayed.best_at,
            close_time=close_time,
        )
        prior = [
            PriorReview(r.checks, r.targets_hit, r.best_at, r.close_time)
            for r in await self._reviews.prior(trade.position_id)
        ]
        checks = fired_checks(state, quarters[-1], usual, prior)
        if not checks:
            return 0
        price = quarters[-1].close
        entered_at = next(f.at for f in simulator.fills if f.kind == "entry")
        facts = render_facts(
            TradeFacts(
                symbol=instrument.symbol,
                strategy=trade.strategy,
                account=account or "unknown",
                side=trade.side,
                entry=entry,
                risk=risk,
                stop=simulator.stop,
                targets=trade.targets,
                targets_hit=simulator.next_target,
                price=price,
                best=replayed.best,
                worst=replayed.worst,
                best_age=close_time - replayed.best_at,
                open_for=close_time - entered_at,
                quarters=quarters[-QUARTERS_SHOWN:],
                hours=hours,
                checks=checks,
            )
        )
        base = NewReview(
            position_id=trade.position_id,
            account_id=trade.account_id,
            symbol=instrument.symbol,
            strategy=trade.strategy,
            close_time=close_time,
            checks=checks,
            targets_hit=simulator.next_target,
            best_at=replayed.best_at,
            price=price,
            progress_r=trade.side.sign * (price - entry) / risk,
            facts=facts,
            status="not_asked",
        )
        review = await self._ask(base)
        stored = await self._reviews.record(review)
        log.info(
            "exit_review",
            instrument=instrument.symbol,
            strategy=trade.strategy,
            checks=list(checks),
            status=review.status,
            action=review.action,
        )
        return int(stored)

    async def _ask(self, base: NewReview) -> NewReview:
        """Claude's answer, or why it was not asked. Usage is recorded for every call."""
        if self._reviewer is None:
            return base
        day_start = Timeframe.D1.floor(self._clock.now())
        if await self._usage.spent_since(day_start) >= self._daily_limit:
            return replace(base, status="skipped_budget")
        prices = await self._usage.model_prices(MODEL, self._clock.now())
        if prices is None:
            log.error("model_price_missing", model=MODEL)
            return replace(base, status="error")
        prompt = await self._usage.ensure_prompt(
            PROMPT_NAME, PROMPT_VERSION, PROMPT_SHA256, PROMPT_BODY, OUTPUT_SCHEMA_VERSION
        )
        try:
            result = await self._reviewer.review(base.facts)
        except Exception as error:
            # One failed call must not stop paper trading. It is stored and logged.
            log.error("exit_review_failed", error=type(error).__name__, detail=str(error)[:200])
            return replace(base, status="error", prompt_version_id=prompt, model=MODEL)
        usage = result.usage
        cost = cost_usd(usage, prices)
        await self._usage.record_usage(
            PURPOSE,
            result.model,
            usage.input_tokens,
            usage.output_tokens,
            usage.cache_read_tokens,
            usage.cache_write_5m_tokens,
            cost,
        )
        advice = result.advice
        return replace(
            base,
            status=result.status,
            prompt_version_id=prompt,
            model=result.model,
            action=advice.action if advice else None,
            reason=advice.reason if advice else None,
            input_tokens=usage.input_tokens + usage.cache_read_tokens + usage.cache_write_5m_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=cost,
            reply=result.reply,
        )

    async def score_finished(self) -> int:
        """Score advice on trades that have finished. Returns how many were scored."""
        pending = await self._reviews.unscored()
        scored = 0
        for position_id in dict.fromkeys(item.position_id for item in pending):
            trade = await self._paper.trade(position_id)
            if trade is None:
                continue
            now = self._clock.now()
            start = Timeframe.M1.floor(trade.created_at)
            minutes = await self._candles.range(
                trade.provider_id, trade.instrument_id, Timeframe.M1, start, now
            )
            funding = await self._market.funding_between(
                trade.provider_id, trade.instrument_id, trade.created_at, now
            )
            own = replay_trade(trade, minutes, funding)
            if not own.simulator.is_finished:
                continue  # Its candles are not all stored yet.
            own_r = r_of(trade, own)
            for item in (p for p in pending if p.position_id == position_id):
                if item.action == "hold":
                    advised_r = own_r
                else:
                    advised = (item.close_time, item.action)
                    advised_r = r_of(trade, replay_trade(trade, minutes, funding, advice=advised))
                await self._reviews.score(item.id, own_r, advised_r, now)
                scored += 1
        return scored
