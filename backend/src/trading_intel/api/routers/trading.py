"""Signals and paper trading. Read-only: nothing here can place or change a trade."""

from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from trading_intel.api.auth import Owner
from trading_intel.api.container import Container, get_container
from trading_intel.api.schemas.trading import (
    NewsView,
    PaperSummary,
    PositionView,
    SignalView,
    TargetView,
)
from trading_intel.core.errors import NotFoundError
from trading_intel.domain.candles import Timeframe
from trading_intel.domain.events import plain

router = APIRouter(prefix="/api/v1", tags=["trading"])

Services = Annotated[Container, Depends(get_container)]


def _money(value: Decimal | None) -> str | None:
    return None if value is None else plain(value)


def _signal(row: dict[str, Any]) -> SignalView:
    return SignalView(
        id=str(row["id"]),
        provider=row["provider"],
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
    _: Owner, services: Services, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> list[SignalView]:
    return [_signal(row) for row in await services.signals.recent(limit)]


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
    _: Owner, services: Services, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> list[PositionView]:
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
        for row in await services.paper.positions(limit)
    ]


@router.get("/paper-trading/summary", response_model=PaperSummary)
async def summary(owner: Owner, services: Services) -> PaperSummary:
    account = await services.signals.ensure_account(owner.email)
    if account is None:
        raise NotFoundError("No paper account.")
    day_start = Timeframe.D1.floor(services.clock.now())
    state = await services.paper.account_state(account.id, account.starting_balance, day_start)
    stats = await services.paper.performance()
    resolved = int(stats["resolved"])
    expectancy = stats["expectancy_r"]
    return PaperSummary(
        starting_balance=plain(account.starting_balance),
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
    )
