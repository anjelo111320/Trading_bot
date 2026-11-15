"""The bot's Binance accounts for the dashboard: demo trading (D048) and the owner's real futures
wallet (D060). Without exchange keys.

The quant worker saves each account once a minute. These routes read what it saved and the
orders it stored, so the API process never holds a key and can never send an order. A close
asked here is only stored: the quant worker, which holds the key, carries it out.
"""

from decimal import Decimal
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Path, Query, Request
from pydantic import ValidationError

from trading_intel.api.auth import Owner, verify_password
from trading_intel.api.container import Container, get_container
from trading_intel.api.schemas.exchange import (
    ArmingUpdate,
    ArmingView,
    ClosedTradeView,
    CloseRequestView,
    EquityPointView,
    ExchangeOpenOrderView,
    ExchangeOrderView,
    ExchangePositionView,
    ExchangeStatusView,
    GridCellView,
    GroupView,
    LimitCeilingsView,
    LimitsUpdate,
    LimitsView,
    LiveStateView,
    ResultsView,
    StatsView,
)
from trading_intel.core.errors import (
    ConflictError,
    ForbiddenError,
    InvalidRequestError,
    NotFoundError,
)
from trading_intel.database.repositories.exchange import CloseRequest
from trading_intel.database.repositories.signals import Account
from trading_intel.domain.events import plain
from trading_intel.performance.orders import OrderFigures, figure_orders
from trading_intel.performance.report import Period, build
from trading_intel.performance.results import Summary, Trade, highest_equity, rebuild
from trading_intel.risk_management.calculators.linear import loss_floor
from trading_intel.risk_management.models import (
    CEILING_DAILY_LOSS,
    CEILING_EXPOSURE,
    CEILING_LEVERAGE,
    CEILING_OPEN_RISK,
    CEILING_RISK_FRACTION,
    RiskProfile,
)
from trading_intel.trade_signals.exchange_accounts import DEMO, LIVE, ExchangeKind

Services = Annotated[Container, Depends(get_container)]
Symbol = Annotated[str, Path(pattern=r"^[A-Z0-9]{2,30}$")]

MONEY: Final = Decimal("0.0001")
# Real trading can be turned on only while the bot's last check of Binance is this recent.
FRESH_SNAPSHOT_SECONDS: Final = 300
# Prices keep 8 places: a 1000PEPE contract trades near 0.009 USDT.
PRICE: Final = Decimal("0.00000001")


async def account_of(kind: ExchangeKind, owner: Owner, services: Container) -> Account:
    """Demo trading's account is made with its budget on first use. The real account exists
    only once the quant worker has seen USDT in the futures wallet (D060)."""
    if kind.budget is not None:
        account = await services.signals.ensure_account(
            owner.email, kind.name, kind.budget, kind.profile, mode=kind.mode
        )
    else:
        account = await services.signals.find_account(owner.email, kind.name)
    if account is None:
        raise NotFoundError(f"No {kind.name} account yet.")
    return account


async def start_of(kind: ExchangeKind, account: Account, services: Container) -> Decimal:
    """Where the account's results start: demo's budget, or what the owner put in (D060)."""
    if kind.budget is not None:
        return account.starting_balance
    return await services.exchange.funded(account.id) or account.starting_balance


def _num(value: Decimal | None) -> str | None:
    """Rounded to 4 places for the page; the stored fills keep Binance's full precision."""
    return None if value is None else plain(value.quantize(MONEY).normalize())


def _price(value: Decimal | None) -> str | None:
    return None if value is None else plain(value.quantize(PRICE).normalize())


def _stats(summary: Summary) -> StatsView:
    return StatsView(
        trades=summary.trades,
        wins=summary.wins,
        losses=summary.losses,
        win_rate=_num(summary.win_rate),
        net=_num(summary.net) or "0",
        pnl=_num(summary.pnl) or "0",
        fees=_num(summary.fees) or "0",
        funding=_num(summary.funding) or "0",
        average_r=_num(summary.average_r),
        average_win=_num(summary.average_win),
        average_loss=_num(summary.average_loss),
        profit_factor=_num(summary.profit_factor),
        best=_num(summary.best),
        worst=_num(summary.worst),
    )


def _groups(rows: list[tuple[str, Summary]]) -> list[GroupView]:
    return [GroupView(name=name, stats=_stats(stats)) for name, stats in rows]


def _trade(trade: Trade) -> ClosedTradeView:
    assert trade.closed_at is not None and trade.strategy is not None
    return ClosedTradeView(
        symbol=trade.symbol,
        side=trade.side,
        strategy=trade.strategy,
        opened_at=trade.opened_at,
        closed_at=trade.closed_at,
        size=plain(trade.size.normalize()),
        entry_price=_price(trade.entry_price),
        exit_price=_price(trade.exit_price),
        pnl=_num(trade.pnl) or "0",
        fees=_num(trade.fees) or "0",
        funding=_num(trade.funding) or "0",
        net=_num(trade.net) or "0",
        r=_num(trade.r),
        won=trade.won,
    )


def _fraction(value: Decimal | None) -> str | None:
    return None if value is None else plain(value.normalize())


async def _limits(services: Container, account: Account) -> LimitsView:
    version, changed_at = await services.signals.profile_version(account.risk_profile_id)
    profile = account.profile
    return LimitsView(
        version=version,
        changed_at=changed_at,
        risk_per_trade=_fraction(profile.max_risk_fraction) or "0",
        open_risk=_fraction(profile.max_open_risk_fraction),
        exposure=_fraction(profile.max_total_exposure_fraction) or "0",
        largest_trade=_fraction(profile.max_position_fraction),
        one_direction=_fraction(profile.max_side_exposure_fraction),
        max_leverage=_fraction(profile.max_leverage) or "1",
        daily_loss=_fraction(profile.max_daily_loss_fraction) or "0",
        daily_profit_stop=_fraction(profile.daily_profit_stop_fraction),
        loss_stop=_fraction(profile.max_total_loss_fraction),
        loss_stop_from_high=profile.loss_stop_from_high,
        ceilings=LimitCeilingsView(
            risk_per_trade=plain(CEILING_RISK_FRACTION.normalize()),
            open_risk=plain(CEILING_OPEN_RISK.normalize()),
            daily_loss=plain(CEILING_DAILY_LOSS.normalize()),
            leverage=plain(CEILING_LEVERAGE.normalize()),
            exposure=plain(CEILING_EXPOSURE.normalize()),
        ),
    )


def _order(row: dict[str, Any], figures: OrderFigures | None = None) -> ExchangeOrderView:
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
        **_figures(figures),
    )


def _figures(figures: OrderFigures | None) -> dict[str, Any]:
    if figures is None:
        return {}
    return {
        "strategy": figures.strategy,
        "value_usdt": _num(figures.value),
        "if_hit_usdt": _num(figures.if_hit),
        "now_usdt": _num(figures.now),
        "trade_state": figures.state,
        "risk_usdt": _num(figures.risk),
        "fill_price": _price(figures.fill_price),
    }


def _close_view(close: CloseRequest) -> CloseRequestView:
    return CloseRequestView(
        id=str(close.id),
        symbol=close.symbol,
        requested_at=close.requested_at,
        done_at=close.done_at,
        outcome=close.outcome,
        detail=close.detail,
    )


def _from_dashboard(services: Container, request: Request) -> None:
    if request.headers.get("origin") not in services.settings.cors_origins:
        raise ForbiddenError("This can be done only from the dashboard.")


async def _ready_to_arm(services: Container, account: Account) -> None:
    """Real trading turns on only while the bot runs and its check of Binance is clean."""
    stored = await services.exchange.status(account.id)
    if stored is None:
        raise ConflictError("The bot has not checked the real account yet.")
    taken_at, body = stored
    if (services.clock.now() - taken_at).total_seconds() > FRESH_SNAPSHOT_SECONDS:
        raise ConflictError("The bot is not running, so real trading stays off.")
    live = body.get("live") or {}
    problems = list(live.get("problems") or [])
    if live.get("checked_at") is None and not problems:
        problems = ["the key is not checked with Binance yet"]
    if problems:
        raise ConflictError("Real trading cannot be turned on: " + "; ".join(problems) + ".")


def exchange_router(kind: ExchangeKind) -> APIRouter:
    """The same routes for each Binance account, under its own prefix."""
    router = APIRouter(prefix=f"/api/v1/exchange-{kind.venue}", tags=[f"exchange-{kind.venue}"])
    label = "the real account" if kind.live else "Binance demo"

    @router.get("/status", response_model=ExchangeStatusView)
    async def status(owner: Owner, services: Services) -> ExchangeStatusView:
        try:
            account = await account_of(kind, owner, services)
        except NotFoundError:
            # The real account: no USDT seen in the futures wallet yet, or no key set.
            return ExchangeStatusView(test_funds=not kind.live, connected=False, capital="0")
        start = await start_of(kind, account, services)
        base = start
        if account.profile.loss_stop_from_high:
            closed, _ = rebuild(*await services.exchange.history(account.id))
            base = highest_equity(closed, start)
        floor = loss_floor(base, account.profile)
        closing = sorted(c.symbol for c in await services.exchange.waiting_closes(account.id))
        # The switch reads as set at once, not at the bot's next minute check (D063, D064).
        armed, armed_at, _ = await services.exchange.arming(account.id, default=kind.starts_on)
        common: dict[str, Any] = {
            "test_funds": not kind.live,
            "capital": plain(start.normalize()),  # Stored with 18 places.
            "loss_floor": None if floor is None else plain(floor.normalize()),
            "loss_stopped_at": await services.exchange.loss_stop(
                account.id, account.risk_profile_id
            ),
            "closing": closing,
            "armed": armed,
        }
        stored = await services.exchange.status(account.id)
        if stored is None:
            return ExchangeStatusView(connected=False, **common)
        taken_at, body = stored
        binance, budget = body["binance"], body["budget"]
        live = body.get("live")
        if live is not None:
            live = {**live, "armed": armed, "armed_at": armed_at}
        return ExchangeStatusView(
            **common,
            connected=True,
            taken_at=taken_at,
            age_seconds=int((services.clock.now() - taken_at).total_seconds()),
            binance_equity=binance["equity"],
            binance_available=binance["available"],
            equity=budget["equity"],
            day_start_equity=budget["day_start_equity"],
            available=budget["available"],
            positions=[ExchangePositionView(**item) for item in body["positions"]],
            orders=[ExchangeOpenOrderView(**item) for item in body["orders"]],
            live=None if live is None else LiveStateView(**live),
        )

    @router.get("/results", response_model=ResultsView)
    async def results(
        owner: Owner, services: Services, period: Annotated[Period, Query()] = "all"
    ) -> ResultsView:
        """Completed trades and their results, rebuilt from Binance's own fills (D057)."""
        account = await account_of(kind, owner, services)
        start = await start_of(kind, account, services)
        fills, funding, entries = await services.exchange.history(account.id)
        report = build(fills, funding, entries, start, services.clock.now(), period)
        return ResultsView(
            test_funds=not kind.live,
            period=report.period,
            since=report.since,
            start_equity=_num(report.start_equity) or "0",
            summary=_stats(report.summary),
            by_coin=_groups(report.by_coin),
            by_strategy=_groups(report.by_strategy),
            by_side=_groups(report.by_side),
            by_day=_groups(report.by_day),
            grid=[
                GridCellView(strategy=strategy, symbol=symbol, stats=_stats(stats))
                for strategy, symbol, stats in report.grid
            ],
            equity=[
                EquityPointView(at=at, equity=_num(value) or "0")
                for at, value in report.curve.points
            ],
            drawdown=_num(report.curve.drawdown) or "0",
            drawdown_fraction=_num(report.curve.drawdown_fraction),
            longest_wins=report.streaks.longest_wins,
            longest_losses=report.streaks.longest_losses,
            current_streak=report.streaks.current,
            median_hold_hours=_num(report.median_hold_hours),
            open_trades=report.open_trades,
            not_from_bot=report.not_from_bot,
            other_fees={asset: _num(amount) or "0" for asset, amount in report.other_fees.items()},
            last_fill_at=report.last_fill_at,
            trades=[_trade(trade) for trade in report.trades],
        )

    @router.get("/limits", response_model=LimitsView)
    async def limits(owner: Owner, services: Services) -> LimitsView:
        """The account's limits now, with the ceilings no setting can pass (D058)."""
        return await _limits(services, await account_of(kind, owner, services))

    @router.put("/limits", response_model=LimitsView)
    async def change_limits(
        owner: Owner, services: Services, body: LimitsUpdate, request: Request
    ) -> LimitsView:
        """Save new limits as a new version, used from the next close. Saving also resumes
        trading after a loss stop, because the stop holds only for the version it was reached
        under (D053). Only the dashboard's own origin may change them."""
        _from_dashboard(services, request)
        account = await account_of(kind, owner, services)
        try:
            profile = RiskProfile.model_validate(
                {
                    **account.profile.model_dump(),
                    "max_risk_fraction": body.risk_per_trade,
                    "max_open_risk_fraction": body.open_risk,
                    "max_total_exposure_fraction": body.exposure,
                    "max_position_fraction": body.largest_trade,
                    "max_side_exposure_fraction": body.one_direction,
                    "max_leverage": body.max_leverage,
                    "max_daily_loss_fraction": body.daily_loss,
                    "daily_profit_stop_fraction": body.daily_profit_stop,
                    "max_total_loss_fraction": body.loss_stop,
                    "loss_stop_from_high": body.loss_stop_from_high,
                }
            )
        except ValidationError as error:
            reasons = "; ".join(str(item.get("msg", "")) for item in error.errors())
            raise InvalidRequestError(f"These limits are not allowed: {reasons}") from error
        version = await services.signals.add_profile_version(account.id, owner.id, profile)
        await services.audit.record(
            owner.email,
            f"exchange_{kind.venue}_limits_changed",
            "risk_profile",
            object_id=f"{account.id}:{version}",
            after=body.model_dump(mode="json"),
            request_id=getattr(request.state, "request_id", None),
        )
        return await _limits(services, await account_of(kind, owner, services))

    @router.get("/orders", response_model=list[ExchangeOrderView])
    async def orders(
        owner: Owner, services: Services, limit: Annotated[int, Query(ge=1, le=200)] = 50
    ) -> list[ExchangeOrderView]:
        account = await account_of(kind, owner, services)
        rows = await services.exchange.orders(account.id, limit)
        fills, funding, entries = await services.exchange.history(account.id)
        closed, still_open = rebuild(fills, funding, entries)
        stored = await services.exchange.status(account.id)
        body = stored[1] if stored else {"positions": [], "orders": []}
        unrealized = {p["symbol"]: Decimal(str(p["unrealized"])) for p in body["positions"]}
        # The owner's own limit orders on the real account never make the bot's entry wait.
        waiting = frozenset(
            o["symbol"]
            for o in body["orders"]
            if o.get("type") == "LIMIT" and o.get("bot") is not False
        )
        figures = figure_orders(
            rows, closed, still_open, entries, unrealized, waiting, services.clock.now()
        )
        return [_order(row, figure) for row, figure in zip(rows, figures, strict=True)]

    @router.post("/positions/{symbol}/close", response_model=CloseRequestView, status_code=202)
    async def close(
        owner: Owner, services: Services, symbol: Symbol, request: Request
    ) -> CloseRequestView:
        """Close the bot's trade on a coin now (D060): its waiting entry is cancelled, its
        position closed at market, then its stop and targets cancelled. The quant worker does it
        within seconds. Only a trade of the bot's can be closed here, and only from the
        dashboard's own origin; the owner's own positions are closed in the Binance app."""
        _from_dashboard(services, request)
        account = await account_of(kind, owner, services)
        stored = await services.exchange.status(account.id)
        body = stored[1] if stored else {"positions": [], "orders": []}
        held = {p["symbol"] for p in body["positions"] if p.get("bot", True)} | {
            o["symbol"] for o in body["orders"] if o.get("type") == "LIMIT" and o.get("bot", True)
        }
        if symbol not in held:
            raise NotFoundError(f"The bot has no open trade on {symbol} in {label}.")
        asked = await services.exchange.request_close(account.id, symbol, owner.email)
        await services.audit.record(
            owner.email,
            f"exchange_{kind.venue}_close_requested",
            "exchange_close_request",
            object_id=str(asked.id),
            after={"account": kind.name, "symbol": symbol},
            request_id=getattr(request.state, "request_id", None),
        )
        return _close_view(asked)

    @router.put("/arming", response_model=ArmingView)
    async def arming(
        owner: Owner, services: Services, body: ArmingUpdate, request: Request
    ) -> ArmingView:
        """The account's trading on or off (D063, D064). Off stops new trades at once; open
        trades keep their stops and targets on Binance. On the real account, on needs the
        owner's password, a running bot and a clean check of the key and the account; demo
        trading's test funds need neither. From the dashboard only, logged."""
        _from_dashboard(services, request)
        account = await account_of(kind, owner, services)
        if body.armed and kind.live:
            services.limiter.check(request.client.host if request.client else "unknown")
            if not body.password or not verify_password(owner.password_hash, body.password):
                await services.audit.record(
                    owner.email, "exchange_live_arm_refused", "exchange_arming",
                    object_id=str(account.id),
                    request_id=getattr(request.state, "request_id", None),
                )  # fmt: skip
                raise ForbiddenError("The password is not right.")
            await _ready_to_arm(services, account)
        await services.exchange.set_armed(account.id, body.armed, owner.email, "dashboard")
        await services.audit.record(
            owner.email,
            f"exchange_{kind.venue}_{'armed' if body.armed else 'disarmed'}",
            "exchange_arming",
            object_id=str(account.id),
            request_id=getattr(request.state, "request_id", None),
        )
        armed, armed_at, _ = await services.exchange.arming(account.id, default=kind.starts_on)
        return ArmingView(armed=armed, armed_at=armed_at)

    @router.get("/closes", response_model=list[CloseRequestView])
    async def closes(
        owner: Owner, services: Services, limit: Annotated[int, Query(ge=1, le=50)] = 10
    ) -> list[CloseRequestView]:
        """The latest closes asked from the dashboard, and what each did."""
        account = await account_of(kind, owner, services)
        return [_close_view(close) for close in await services.exchange.closes(account.id, limit)]

    return router


router = exchange_router(DEMO)
live_router = exchange_router(LIVE)
