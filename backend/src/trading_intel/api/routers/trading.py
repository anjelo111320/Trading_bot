"""Signals and paper trading. Read-only: nothing here can place or change a trade."""

from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from trading_intel.api.auth import Owner
from trading_intel.api.container import Container, get_container
from trading_intel.api.schemas.trading import (
    CoinCardView,
    CoinConditionsView,
    EntryQualityView,
    EvidenceView,
    FillView,
    LiveResultView,
    NewsSignalView,
    NewsStoryView,
    NewsView,
    PaperSummary,
    PositionView,
    ScorecardView,
    SignalScoreView,
    SignalTradeView,
    SignalView,
    StrategyCellView,
    TargetView,
    TradeView,
)
from trading_intel.core.errors import NotFoundError
from trading_intel.database.repositories.reference import ProviderInstrument
from trading_intel.database.repositories.signals import (
    DEMO_ACCOUNT,
    DEMO_BALANCE,
    EXCHANGE_DEMO_ACCOUNT,
    EXCHANGE_DEMO_BUDGET,
    EXCHANGE_DEMO_MODE,
    EXCHANGE_LIVE_ACCOUNT,
    PAPER_ACCOUNT,
    PORTFOLIO_ACCOUNT,
    PORTFOLIO_BALANCE,
    STARTING_BALANCE,
    Account,
    SignalFilter,
)
from trading_intel.domain.candles import Timeframe
from trading_intel.domain.events import plain
from trading_intel.domain.instruments import InstrumentType
from trading_intel.domain.signals import Side
from trading_intel.news_intelligence.reading import RULE_VERSION, THRESHOLD, WINDOW, NewsSignal
from trading_intel.performance.results import rebuild
from trading_intel.performance.scorecard import (
    FIRST_HOUR,
    CoinCard,
    EnteredTrade,
    EntryQuality,
    Evidence,
    LiveResult,
    Scored,
    cards,
    dedupe,
    first_hour_r,
    slippage_r,
)
from trading_intel.performance.signal_trades import (
    ENTERED,
    ResultFilter,
    SignalTrade,
    exchange_trades,
    paper_trades,
    wanted,
)
from trading_intel.risk_management.models import RiskProfile
from trading_intel.technical_analysis.series import CandleSeries
from trading_intel.technical_analysis.volatility import atr
from trading_intel.trade_signals.baseline import LOOSE_NAME
from trading_intel.trade_signals.baseline import STRATEGY_NAME as BASELINE_NAME
from trading_intel.trade_signals.fvg_choch_strategy import STRATEGY_NAME as FVG_NAME
from trading_intel.trade_signals.news_move_strategy import STRATEGY_NAME as NEWS_MOVE_NAME
from trading_intel.trade_signals.pattern_strategy import STRATEGY_NAME as PATTERN_NAME
from trading_intel.trade_signals.portfolio import (
    EXCHANGE_DEMO_PROFILE,
    LEFT_OUT,
    PLAN_PROFILE,
    SWITCHED_OFF,
)
from trading_intel.trade_signals.trend_strategy import STRATEGY_NAME as TREND_NAME

router = APIRouter(prefix="/api/v1", tags=["trading"])

Services = Annotated[Container, Depends(get_container)]
# The tested strategies' account, the demo bot's 100 USDT account (D044), or the money
# plan's 1,000 USDT account (D045). Whichever side creates an account gives it its limits.
AccountName = Annotated[Literal["paper", "demo", "portfolio"], Query()]
# Signals also exist for the Binance demo account (D048) and the owner's real futures wallet
# (D060). Their positions live on Binance.
SignalAccountName = Annotated[
    Literal["paper", "demo", "portfolio", "binance", "binance_live"], Query()
]
ACCOUNTS: Final[dict[str, tuple[str, Decimal, RiskProfile | None, str]]] = {
    "paper": (PAPER_ACCOUNT, STARTING_BALANCE, None, "paper"),
    "demo": (DEMO_ACCOUNT, DEMO_BALANCE, None, "paper"),
    "portfolio": (PORTFOLIO_ACCOUNT, PORTFOLIO_BALANCE, PLAN_PROFILE, "paper"),
    "binance": (
        EXCHANGE_DEMO_ACCOUNT,
        EXCHANGE_DEMO_BUDGET,
        EXCHANGE_DEMO_PROFILE,
        EXCHANGE_DEMO_MODE,
    ),
}
# Signal accounts whose trades live on Binance, rebuilt from its fills (D057).
ON_BINANCE: Final = frozenset({"binance", "binance_live"})
# The Signals page's filters (D065). The period runs back from now; today starts at 00:00 UTC.
SignalPeriod = Literal["today", "7d", "30d", "all"]
PERIOD_DAYS: Final[dict[str, int]] = {"7d": 7, "30d": 30}
# Prices keep 8 places, as on the Bot page; USDT results keep 4.
PRICE: Final = Decimal("0.00000001")
MONEY: Final = Decimal("0.0001")
# The coin scorecard (D068): every account's trades, the strategies in the page's order, R to
# 2 places, a spread from a book no older than 10 minutes, and the 1H ATR over 60 hours.
SCORED_ACCOUNTS: Final = ("paper", "demo", "portfolio", "binance", "binance_live")
SCORED_STRATEGIES: Final = (
    TREND_NAME,
    PATTERN_NAME,
    FVG_NAME,
    BASELINE_NAME,
    LOOSE_NAME,
    NEWS_MOVE_NAME,
)
CLOSED_STATES: Final = frozenset({"won", "lost", "even"})
R_PLACES: Final = Decimal("0.01")
SPREAD_PLACES: Final = Decimal("0.1")
BOOK_FRESH: Final = timedelta(minutes=10)
ATR_HOURS: Final = 60
ATR_PERIOD: Final = 14


async def _account(owner: Owner, services: Services, which: str) -> Account:
    name, balance, limits, mode = ACCOUNTS[which]
    account = await services.signals.ensure_account(owner.email, name, balance, limits, mode=mode)
    if account is None:
        raise NotFoundError("No paper account.")
    return account


async def _signal_account(owner: Owner, services: Services, which: str) -> Account | None:
    if which == "binance_live":
        # Made only by the quant worker, once it sees USDT in the futures wallet (D060).
        return await services.signals.find_account(owner.email, EXCHANGE_LIVE_ACCOUNT)
    return await _account(owner, services, which)


async def _trades(services: Services, which: str, account: Account) -> dict[UUID, SignalTrade]:
    """Each signal's trade in the account, by signal (D065)."""
    if which not in ON_BINANCE:
        return paper_trades(await services.paper.by_signal(account.id))
    closed, still_open = rebuild(*await services.exchange.history(account.id))
    stored = await services.exchange.status(account.id)
    body = stored[1] if stored else {"positions": [], "orders": []}
    # The owner's own positions and orders on the real account are never the bot's (D060).
    unrealized = {
        p["symbol"]: Decimal(str(p["unrealized"]))
        for p in body["positions"]
        if p.get("bot") is not False
    }
    waiting = frozenset(
        o["symbol"]
        for o in body["orders"]
        if o.get("type") == "LIMIT" and o.get("bot") is not False
    )
    return exchange_trades(
        await services.exchange.entries(account.id),
        [*closed, *still_open],
        unrealized,
        waiting,
        services.clock.now(),
    )


def _since(services: Services, period: SignalPeriod) -> datetime | None:
    now = services.clock.now()
    if period == "today":
        return Timeframe.D1.floor(now)
    days = PERIOD_DAYS.get(period)
    return None if days is None else now - timedelta(days=days)


def _money(value: Decimal | None) -> str | None:
    return None if value is None else plain(value)


def _rounded(value: Decimal | None, places: Decimal) -> str | None:
    return None if value is None else plain(value.quantize(places).normalize())


def _trade_view(trade: SignalTrade | None) -> SignalTradeView | None:
    if trade is None:
        return None
    return SignalTradeView(
        state=trade.state,
        opened_at=trade.opened_at,
        closed_at=trade.closed_at,
        entry_price=_rounded(trade.entry_price, PRICE),
        exit_price=_rounded(trade.exit_price, PRICE),
        net=_rounded(trade.net, MONEY),
    )


def _signal(row: dict[str, Any], trade: SignalTrade | None = None) -> SignalView:
    return SignalView(
        id=str(row["id"]),
        provider=row["provider"],
        strategy=row["strategy"],
        instrument_id=row["instrument_id"],
        timeframe=Timeframe(row["timeframe"]),
        action=row["action"],
        entry_type=row["entry_type"],
        state=row["state"],
        market_price=plain(row["market_price"]),
        entry_price=_money(row["entry_price"]),
        stop_loss=_money(row["stop_loss"]),
        targets=[TargetView(**item) for item in row["targets"] or []],
        quantity=_money(row["quantity"]),
        notional=_money(row["notional"]),
        max_account_risk=_money(row["max_account_risk"]),
        estimated_fees=_money(row["fees_est"]),
        estimated_funding=_money(row["funding_est"]),
        reward_risk_net=_money(row["reward_risk_net"]),
        risk_share=row.get("risk_share"),
        signal_score=SignalScoreView(**score) if (score := row.get("signal_score")) else None,
        decision=row["decision"],
        rejection_codes=list(row["rejection_codes"]),
        setup_quality_score=_money(row["setup_quality_score"]),
        news_alignment=row["news_alignment"],
        data_reliability_score=plain(row["data_reliability_score"]),
        probability_status=row["probability_status"],
        technical_explanation=row["technical_explanation"],
        fundamental_explanation=row["fundamental_explanation"],
        supporting_evidence=row["supporting_evidence"],
        conflicting_evidence=row["conflicting_evidence"],
        invalidation_conditions=row["invalidation_conditions"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        data_as_of=row["data_as_of"],
        trade=_trade_view(trade),
    )


@router.get("/signals", response_model=list[SignalView])
async def signals(
    owner: Owner,
    services: Services,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    account: SignalAccountName = "paper",
    instrument_id: Annotated[int | None, Query(ge=1)] = None,
    strategy: Annotated[str | None, Query(pattern=r"^[a-z0-9_]{1,64}$")] = None,
    action: Annotated[Literal["BUY", "SELL"] | None, Query()] = None,
    decision: Annotated[Literal["APPROVED", "REJECTED"] | None, Query()] = None,
    result: Annotated[ResultFilter | None, Query()] = None,
    period: Annotated[SignalPeriod, Query()] = "all",
) -> list[SignalView]:
    """The account's signals, newest first, each with what became of its trade (D065).
    Every filter is optional; `result` filters by the trade's state."""
    chosen = await _signal_account(owner, services, account)
    if chosen is None:
        return []
    filters = SignalFilter(
        instrument_id=instrument_id,
        strategy=strategy,
        action=action,
        decision=decision,
        since=_since(services, period),
    )
    # The result filter needs every match's trade before the limit is applied.
    rows = await services.signals.recent(chosen.id, None if result else limit, filters)
    trades = await _trades(services, account, chosen)
    if result is not None:
        rows = [row for row in rows if wanted(trades.get(row["id"]), result)][:limit]
    return [_signal(row, trades.get(row["id"])) for row in rows]


@router.get("/signals/{signal_id}", response_model=SignalView)
async def signal(
    owner: Owner, services: Services, signal_id: UUID, account: SignalAccountName = "paper"
) -> SignalView:
    """One of the account's signals with its trade, for the Bot page's chart link (D065)."""
    chosen = await _signal_account(owner, services, account)
    rows = (
        []
        if chosen is None
        else await services.signals.recent(chosen.id, 1, SignalFilter(signal_id=signal_id))
    )
    if chosen is None or not rows:
        raise NotFoundError("No such signal in this account.")
    trades = await _trades(services, account, chosen)
    return _signal(rows[0], trades.get(rows[0]["id"]))


def _entered(row: dict[str, Any], trade: SignalTrade | None, symbol: str) -> EnteredTrade | None:
    """The trade a signal opened, with its result in R once closed, or None if it never
    entered. R is the net result over the risk the engine planned."""
    if trade is None or trade.state not in ENTERED:
        return None
    if trade.opened_at is None or trade.entry_price is None:
        return None
    planned = row.get("max_account_risk")
    result = None
    if trade.state in CLOSED_STATES and trade.net is not None and planned:
        result = trade.net / Decimal(planned)
    return EnteredTrade(
        symbol, row["strategy"], Side.LONG if row["action"] == "BUY" else Side.SHORT,
        Decimal(row["entry_price"]), Decimal(row["stop_loss"]), trade.entry_price,
        trade.opened_at, result,
    )  # fmt: skip


async def _conditions(
    services: Services, item: ProviderInstrument, now: datetime, today: list[dict[str, Any]]
) -> CoinConditionsView:
    """The coin now: its 1H volatility, its spread, its unrepaired gaps and today's signals."""
    provider, instrument = item.provider_id, item.instrument.id
    hours = await services.candles.range(
        provider, instrument, Timeframe.H1, now - timedelta(hours=ATR_HOURS), now
    )
    volatility = None
    if len(hours) > ATR_PERIOD:
        value = Decimal(str(float(atr(CandleSeries.of(hours), ATR_PERIOD)[-1])))
        volatility = value / hours[-1].close * 100
    book = await services.snapshots.latest_book(provider, instrument, now)
    spread = None
    if book is not None and now - book[0] <= BOOK_FRESH and book[1] > 0 and book[2] > 0:
        spread = (book[2] - book[1]) / ((book[1] + book[2]) / 2) * 10_000
    gaps = await services.gaps.list(
        provider_id=provider, instrument_id=instrument, states=("detected", "repairing")
    )
    mine = [row for row in today if row["instrument_id"] == instrument]
    refusals = Counter(code for row in mine for code in row["rejection_codes"] or ())
    return CoinConditionsView(
        atr_percent=_rounded(volatility, R_PLACES),
        spread_bps=_rounded(spread, SPREAD_PLACES),
        open_gaps=len(gaps),
        signals_today=len(mine),
        approved_today=sum(1 for row in mine if row["decision"] == "APPROVED"),
        top_refusal=refusals.most_common(1)[0][0] if refusals else None,
    )


def _live_view(result: LiveResult) -> LiveResultView:
    return LiveResultView(
        entered=result.entered,
        closed=result.closed,
        won=result.won,
        mean_r=_rounded(result.mean_r, R_PLACES),
    )


def _entry_view(quality: EntryQuality) -> EntryQualityView:
    return EntryQualityView(
        trades=quality.trades,
        slippage_r=_rounded(quality.slippage_r, R_PLACES),
        first_hour_r=_rounded(quality.first_hour_r, R_PLACES),
        went_against=quality.went_against,
    )


def _evidence_view(evidence: Evidence | None) -> EvidenceView | None:
    if evidence is None:
        return None
    return EvidenceView(
        trades=evidence.trades,
        mean_r=plain(evidence.mean_r),
        low=plain(evidence.low),
        high=plain(evidence.high),
        source=evidence.source,
    )


def _card_view(card: CoinCard, instrument_id: int, conditions: CoinConditionsView) -> CoinCardView:
    return CoinCardView(
        symbol=card.symbol,
        instrument_id=instrument_id,
        live=_live_view(card.live),
        entries=_entry_view(card.entries),
        conditions=conditions,
        strategies=[
            StrategyCellView(
                strategy=cell.strategy,
                evidence=_evidence_view(cell.evidence),
                untested=cell.untested,
                left_out=cell.left_out,
                live=_live_view(cell.live),
                entries=_entry_view(cell.entries),
            )
            for cell in card.strategies
        ],
    )


@router.get("/coins/scorecard", response_model=ScorecardView)
async def scorecard(owner: Owner, services: Services) -> ScorecardView:
    """Each coin's scorecard (D068): what the studies found for each strategy, what every
    account's trades did, how good their entries were, and the coin today. Python's numbers
    only; nothing here changes a trade."""
    now = services.clock.now()
    listed = [
        item
        for item in await services.reference.provider_instruments("binance_usdm")
        if item.instrument.instrument_type is InstrumentType.LINEAR_PERPETUAL
    ]
    symbols = {item.instrument.id: item.instrument.symbol for item in listed}
    live = await _signal_account(owner, services, "binance_live")
    counted: Literal["binance_live", "binance"] = "binance_live" if live else "binance"
    since = Timeframe.D1.floor(now)
    entered: list[EnteredTrade] = []
    today: list[dict[str, Any]] = []
    for which in SCORED_ACCOUNTS:
        account = live if which == "binance_live" else await _signal_account(owner, services, which)
        if account is None:
            continue
        trades = await _trades(services, which, account)
        rows = await services.signals.recent(account.id, None)
        if which == counted:
            today = [row for row in rows if row["created_at"] >= since]
        for row in rows:
            symbol = symbols.get(row["instrument_id"])
            trade = _entered(row, trades.get(row["id"]), symbol) if symbol else None
            if trade is not None:
                entered.append(trade)
    by_symbol = {item.instrument.symbol: item for item in listed}
    scored: list[Scored] = []
    for trade in dedupe(entered):
        hour = None
        if now >= trade.opened_at + FIRST_HOUR:
            item = by_symbol[trade.symbol]
            minutes = await services.candles.range(
                item.provider_id, item.instrument.id, Timeframe.M1,
                trade.opened_at, trade.opened_at + FIRST_HOUR,
            )  # fmt: skip
            hour = first_hour_r(trade, minutes)
        scored.append(Scored(trade, slippage_r(trade), hour))
    names = [item.instrument.symbol for item in listed]
    # A strategy the owner switched off counts as left out on every coin (D070).
    off = LEFT_OUT | {(strategy, symbol) for strategy in SWITCHED_OFF for symbol in names}
    found = cards(names, SCORED_STRATEGIES, scored, off)
    coins = [
        _card_view(card, item.instrument.id, await _conditions(services, item, now, today))
        for card, item in zip(found, listed, strict=True)
    ]
    return ScorecardView(as_of=now, account=counted, coins=coins)


@router.get("/news", response_model=list[NewsView])
async def news(
    _: Owner, services: Services, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> list[NewsView]:
    return [
        NewsView(
            id=str(row["id"]),
            headline=row["headline"],
            source=row["source"],
            credibility_tier=row["credibility_tier"],
            url=row["url"],
            published_at=row["published_at"],
            retrieved_at=row["retrieved_at"],
            relevance=_money(row["relevance"]),
            event_type=row["event_type"],
            sentiment=row["sentiment"],
            potential_impact=row["potential_impact"],
            certainty=row["certainty"],
            possibly_misleading=row["possibly_misleading"],
            ai_summary=row["ai_summary"],
            classified=row["ai_summary"] is not None,
        )
        for row in await services.news.visible_at(services.clock.now(), limit)
    ]


@router.get("/news/signal", response_model=NewsSignalView)
async def news_signal(_: Owner, services: Services, instrument_id: int) -> NewsSignalView:
    """The coin's news reading now: Python's sum of Claude's labels (D055). Untested."""
    reading = await NewsSignal(services.news).reading(instrument_id, services.clock.now())
    return NewsSignalView(
        instrument_id=instrument_id,
        at=reading.at,
        rule_version=RULE_VERSION,
        direction=reading.direction,
        score=plain(reading.score),
        threshold=plain(THRESHOLD),
        window_hours=int(WINDOW.total_seconds() // 3600),
        stories=[
            NewsStoryView(
                headline=story.headline,
                published_at=story.published_at,
                sentiment=story.sentiment,
                impact=story.impact,
                relevance=plain(story.relevance),
                weight=plain(story.weight),
            )
            for story in reading.stories
        ],
    )


@router.get("/paper-trading/positions", response_model=list[PositionView])
async def positions(
    owner: Owner,
    services: Services,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    account: AccountName = "paper",
) -> list[PositionView]:
    chosen = await _account(owner, services, account)
    return [
        PositionView(
            id=str(row["id"]),
            symbol=row["symbol"],
            side=row["side"],
            status=row["status"],
            planned_quantity=plain(row["planned_quantity"]),
            open_quantity=plain(row["open_quantity"]),
            average_entry=_money(row["average_entry"]),
            stop_loss=_money(row["stop_loss"]),
            realized_pnl=plain(row["realized_pnl"]),
            costs_paid=plain(row["costs_paid"]),
            opened_at=row["opened_at"],
            closed_at=row["closed_at"],
            signal_state=row["signal_state"],
            reconstructed=bool(row["reconstructed"]),
        )
        for row in await services.paper.positions(chosen.id, limit)
    ]


def _trade(row: dict[str, Any]) -> TradeView:
    return TradeView(
        id=str(row["id"]),
        instrument_id=row["instrument_id"],
        symbol=row["symbol"],
        strategy=row["strategy"],
        timeframe=Timeframe(row["timeframe"]),
        side=row["side"],
        status=row["status"],
        signal_state=row["signal_state"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        planned_entry=plain(row["planned_entry"]),
        average_entry=_money(row["average_entry"]),
        stop_loss=plain(row["stop_loss"]),
        current_stop=plain(row["current_stop"]),
        targets=[plain(Decimal(price)) for price in row["targets"] or []],
        planned_quantity=plain(row["planned_quantity"]),
        open_quantity=plain(row["open_quantity"]),
        realized_pnl=plain(row["realized_pnl"]),
        costs_paid=plain(row["costs_paid"]),
        opened_at=row["opened_at"],
        closed_at=row["closed_at"],
        outcome=row["outcome"],
        r_multiple=_money(row["r_multiple"]),
        explanation=row["technical_explanation"],
        max_account_risk=_money(row.get("max_account_risk")),
        risk_share=row.get("risk_share"),
        evidence_share=row.get("evidence_share"),
        fills=[
            FillView(
                kind=fill["kind"],
                at=fill["at"],
                price=_money(Decimal(fill["price"])) if fill["price"] is not None else None,
                quantity=plain(Decimal(fill["quantity"])),
                fee=plain(Decimal(fill["fee"])),
                funding=plain(Decimal(fill["funding"])),
                reconstructed=fill["reconstructed"],
            )
            for fill in row["fills"] or []
        ],
    )


@router.get("/paper-trading/trades", response_model=list[TradeView])
async def trades(
    owner: Owner,
    services: Services,
    account: AccountName = "paper",
    instrument_id: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[TradeView]:
    chosen = await _account(owner, services, account)
    return [_trade(row) for row in await services.paper.trades(chosen.id, instrument_id, limit)]


@router.get("/paper-trading/summary", response_model=PaperSummary)
async def summary(owner: Owner, services: Services, account: AccountName = "paper") -> PaperSummary:
    chosen = await _account(owner, services, account)
    day_start = Timeframe.D1.floor(services.clock.now())
    state = await services.paper.account_state(chosen.id, chosen.starting_balance, day_start)
    stats = await services.paper.performance(chosen.id)
    resolved = int(stats["resolved"])
    expectancy = stats["expectancy_r"]
    return PaperSummary(
        account=account,
        starting_balance=plain(chosen.starting_balance),
        equity=plain(state.equity),
        open_positions=state.open_positions,
        resolved_trades=resolved,
        wins=int(stats["wins"]),
        losses=int(stats["losses"]),
        unfilled=int(stats["unfilled"]),
        net_pnl=plain(stats["net_pnl"]),
        costs=plain(stats["costs"]),
        win_rate=int(stats["wins"]) / resolved if resolved else None,
        expectancy_r=float(expectancy) if expectancy is not None else None,
        day_start_equity=plain(state.day_start_equity),
        open_risk=plain(state.open_risk),
        max_open_risk=_money(chosen.profile.max_open_risk_fraction),
        daily_profit_stop=_money(chosen.profile.daily_profit_stop_fraction),
    )
