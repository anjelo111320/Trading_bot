"""Binance demo trading for the dashboard (D048). Read-only, and without exchange keys.

The quant worker saves the account once a minute. This router only reads what it saved and
the orders it stored, so the API process never holds a key and can never send an order.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from trading_intel.api.auth import Owner
from trading_intel.api.container import Container, get_container
from trading_intel.api.schemas.exchange import (
    ExchangeOpenOrderView,
    ExchangeOrderView,
    ExchangePositionView,
    ExchangeStatusView,
)
from trading_intel.core.errors import NotFoundError
from trading_intel.database.repositories.signals import (
    EXCHANGE_DEMO_ACCOUNT,
    EXCHANGE_DEMO_BUDGET,
    EXCHANGE_DEMO_MODE,
    Account,
)
from trading_intel.domain.events import plain
from trading_intel.risk_management.calculators.linear import loss_floor
from trading_intel.trade_signals.portfolio import EXCHANGE_DEMO_PROFILE

router = APIRouter(prefix="/api/v1/exchange-demo", tags=["exchange-demo"])

Services = Annotated[Container, Depends(get_container)]


async def demo_account(owner: Owner, services: Container) -> Account:
    account = await services.signals.ensure_account(
        owner.email, EXCHANGE_DEMO_ACCOUNT, EXCHANGE_DEMO_BUDGET, EXCHANGE_DEMO_PROFILE,
        mode=EXCHANGE_DEMO_MODE,
    )  # fmt: skip
    if account is None:
        raise NotFoundError("No Binance demo account.")
    return account


@router.get("/status", response_model=ExchangeStatusView)
async def status(owner: Owner, services: Services) -> ExchangeStatusView:
    account = await demo_account(owner, services)
    capital = plain(account.starting_balance.normalize())  # Stored with 18 places.
    floor = loss_floor(account.starting_balance, account.profile)
    limits: dict[str, Any] = {
        "loss_floor": None if floor is None else plain(floor.normalize()),
        "loss_stopped_at": await services.exchange.loss_stop(account.id, account.risk_profile_id),
    }
    stored = await services.exchange.status(account.id)
    if stored is None:
        return ExchangeStatusView(connected=False, capital=capital, **limits)
    taken_at, body = stored
    binance, budget = body["binance"], body["budget"]
    return ExchangeStatusView(
        **limits,
        connected=True,
        taken_at=taken_at,
        age_seconds=int((services.clock.now() - taken_at).total_seconds()),
        binance_equity=binance["equity"],
        binance_available=binance["available"],
        capital=capital,
        equity=budget["equity"],
        day_start_equity=budget["day_start_equity"],
        available=budget["available"],
        positions=[ExchangePositionView(**item) for item in body["positions"]],
        orders=[ExchangeOpenOrderView(**item) for item in body["orders"]],
    )


def _order(row: dict[str, Any]) -> ExchangeOrderView:
    request: dict[str, Any] = row["request"] or {}
    response: dict[str, Any] = row["response"] or {}
    error: str | None = row["error"]
    outcome = "accepted" if row["response"] is not None else (
        "no reply" if error and error.startswith("no reply") else "refused"
    )  # fmt: skip
    average = response.get("avgPrice")
    return ExchangeOrderView(
        created_at=row["created_at"],
        symbol=row["symbol"],
        kind=row["kind"],
        side=request.get("side"),
        # A cancel sends no order type. It is named, so the page never shows it as a new order.
        type=request.get("type") or ("CANCEL" if "cancel" in request else None),
        quantity=request.get("quantity"),
        trigger=request.get("triggerPrice"),
        executed=response.get("executedQty"),
        average_price=average if average not in (None, "0", "0.00") else None,
        outcome=outcome,
        error=error,
    )


@router.get("/orders", response_model=list[ExchangeOrderView])
async def orders(
    owner: Owner, services: Services, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> list[ExchangeOrderView]:
    account = await demo_account(owner, services)
    return [_order(row) for row in await services.exchange.orders(account.id, limit)]
