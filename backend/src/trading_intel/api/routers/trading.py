"""Signals and paper trading. Read-only: nothing here can place or change a trade."""

from decimal import Decimal
from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, Depends, Query

from trading_intel.api.auth import Owner
from trading_intel.api.container import Container, get_container
from trading_intel.api.schemas.trading import (
    FillView,
    NewsView,
    PaperSummary,
    PositionView,
    SignalScoreView,
    SignalView,
    TargetView,
    TradeView,
)
from trading_intel.core.errors import NotFoundError
from trading_intel.database.repositories.signals import (
    DEMO_ACCOUNT,
    DEMO_BALANCE,
    EXCHANGE_DEMO_ACCOUNT,
    EXCHANGE_DEMO_BUDGET,
    EXCHANGE_DEMO_MODE,
    PAPER_ACCOUNT,
    PORTFOLIO_ACCOUNT,
    PORTFOLIO_BALANCE,
    STARTING_BALANCE,
    Account,
)
from trading_intel.domain.candles import Timeframe
from trading_intel.domain.events import plain
from trading_intel.risk_management.models import RiskProfile
from trading_intel.trade_signals.portfolio import PLAN_PROFILE

router = APIRouter(prefix="/api/v1", tags=["trading"])

Services = Annotated[Container, Depends(get_container)]
# The tested strategies' account, the demo bot's 100 USDT account (D044), or the money
# plan's 1,000 USDT account (D045). Whichever side creates an account gives it its limits.
AccountName = Annotated[Literal["paper", "demo", "portfolio"], Query()]
# Signals also exist for the Binance demo account (D048). Its positions live on Binance.
SignalAccountName = Annotated[Literal["paper", "demo", "portfolio", "binance"], Query()]
ACCOUNTS: Final[dict[str, tuple[str, Decimal, RiskProfile | None, str]]] = {
    "paper": (PAPER_ACCOUNT, STARTING_BALANCE, None, "paper"),
    "demo": (DEMO_ACCOUNT, DEMO_BALANCE, None, "paper"),
    "portfolio": (PORTFOLIO_ACCOUNT, PORTFOLIO_BALANCE, PLAN_PROFILE, "paper"),
    "binance": (EXCHANGE_DEMO_ACCOUNT, EXCHANGE_DEMO_BUDGET, PLAN_PROFILE, EXCHANGE_DEMO_MODE),
}


async def _account(owner: Owner, services: Services, which: str) -> Account:
    name, balance, limits, mode = ACCOUNTS[which]
    account = await services.signals.ensure_account(owner.email, name, balance, limits, mode=mode)
    if account is None:
        raise NotFoundError("No paper account.")
    return account


def _money(value: Decimal | None) -> str | None:
    return None if value is None else plain(value)


def _signal(row: dict[str, Any]) -> SignalView:
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
    )


@router.get("/signals", response_model=list[SignalView])
async def signals(
    owner: Owner,
    services: Services,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    account: SignalAccountName = "paper",
) -> list[SignalView]:
    chosen = await _account(owner, services, account)
    return [_signal(row) for row in await services.signals.recent(chosen.id, limit)]


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
