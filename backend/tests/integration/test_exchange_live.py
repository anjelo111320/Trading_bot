"""The owner's real futures wallet (D060), on real PostgreSQL with a fake exchange.

Nothing here reaches Binance. The fake exchange stands in for the real account, and a fake
hourly check stands in for Binance's answer about the key.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from typing import Any

import asyncpg
import pytest

from tests.exchange_fakes import FakeGateway
from tests.integration import test_trading_flow as flow
from tests.integration.support import SUPERUSER_URL
from tests.integration.test_trading_flow import (
    BASELINE,
    EMAIL,
    NOW,
    PATTERN,
    TREND,
    World,
    plan_setup,
    rows,
)
from trading_intel.core.clock import FixedClock
from trading_intel.database.repositories.exchange import ExchangeRepository
from trading_intel.database.repositories.signals import Account
from trading_intel.entrypoints.quant_worker import ExchangeLink, TradingLoop
from trading_intel.execution.binance_futures import BinanceError
from trading_intel.execution.key_check import AccountCheck
from trading_intel.execution.trader import FuturesTrader, OrderRecord
from trading_intel.trade_signals.exchange_accounts import DEMO, LIVE

pytestmark = pytest.mark.integration

world = flow.world  # The trading flow's fixture: one coin, a live book and an owner.

OWNER_ETH = {"symbol": "ETHUSDT", "positionAmt": "-0.5", "entryPrice": "3000", "notional": "1500"}


def repository(world: World) -> ExchangeRepository:
    return ExchangeRepository(world.signals._rules._engine)


async def live_account(world: World, equity: D = D(150)) -> Account:
    account = await world.records.ensure_account(
        EMAIL, LIVE.name, equity, LIVE.profile, mode=LIVE.mode
    )
    assert account is not None
    return account


def link(world: World, exchange: FakeGateway, problems: tuple[str, ...] = ()) -> ExchangeLink:
    async def check() -> AccountCheck:
        return AccountCheck(problems, ip_restricted=True)

    return ExchangeLink(LIVE, FuturesTrader(exchange, own_only=True), repository(world), check)


def trading(world: World, *links: ExchangeLink) -> TradingLoop:
    return TradingLoop(
        world.signals, None, world.records, EMAIL, world.provider_id,  # type: ignore[arg-type]
        {world.instrument.id: world.instrument}, FixedClock(NOW), exchanges=links,
    )  # fmt: skip


async def bot_entry(world: World, account: Account, key: str = "sol-trade") -> None:
    """An entry the bot sent, as the plan records it: with its trade key and stop."""
    sent = OrderRecord(
        world.instrument.symbol, "entry", "ati-x-entry", {"type": "MARKET"}, {"orderId": 1}
    )
    await repository(world).record(account.id, None, sent, trade_key=key, stop_price=D("98"))


async def test_a_real_account_can_exist_and_no_other_mode_can(world: World) -> None:
    account = await live_account(world)
    [stored] = await rows(f"SELECT mode FROM trading_accounts WHERE id = '{account.id}'")
    assert stored["mode"] == "exchange_live"
    with pytest.raises(Exception, match="trading_accounts_mode_check"):
        await world.records.ensure_account(EMAIL, "Elsewhere", D(1), mode="exchange_other")


async def test_a_trade_seen_to_end_is_no_longer_the_bots(world: World) -> None:
    account = await live_account(world)
    orders = repository(world)
    await bot_entry(world, account)
    assert await orders.open_trades(account.id) == {world.instrument.symbol: (D(98), "sol-trade")}
    assert await orders.end_trade(
        account.id, "sol-trade", world.instrument.symbol, "flat_on_binance"
    )
    assert not await orders.end_trade(
        account.id, "sol-trade", world.instrument.symbol, "flat_on_binance"
    ), "recorded once"
    assert await orders.open_trades(account.id) == {}
    assert world.instrument.symbol in await orders.stops(account.id), "demo's view is unchanged"


async def test_a_close_waits_once_per_coin_and_is_finished_once(world: World) -> None:
    account = await live_account(world)
    orders = repository(world)
    first = await orders.request_close(account.id, "SOLUSDT", EMAIL)
    again = await orders.request_close(account.id, "SOLUSDT", EMAIL)
    assert again.id == first.id and [c.id for c in await orders.waiting_closes(account.id)] == [
        first.id
    ]
    await orders.finish_close(first.id, "closed", None)
    await orders.finish_close(first.id, "failed", "late")  # A finished close stays as it was.
    [done] = await orders.closes(account.id)
    assert done.outcome == "closed" and done.done_at is not None and done.detail is None
    assert await orders.waiting_closes(account.id) == []
    connection = await asyncpg.connect(SUPERUSER_URL)
    try:
        with pytest.raises(asyncpg.PostgresError):
            await connection.execute(
                "UPDATE exchange_close_requests SET outcome = 'failed' WHERE id = $1", first.id
            )
        with pytest.raises(asyncpg.PostgresError):
            await connection.execute("DELETE FROM exchange_close_requests")
    finally:
        await connection.close()


async def test_arming_is_off_until_the_owner_sets_it_and_keeps_its_history(world: World) -> None:
    account = await live_account(world)
    orders = repository(world)
    assert (await orders.arming(account.id))[0] is False
    await orders.set_armed(account.id, True, EMAIL, "test arm")
    armed, at, by = await orders.arming(account.id)
    assert armed and at is not None and by == EMAIL
    await orders.set_armed(account.id, False, EMAIL, "test disarm")
    assert (await orders.arming(account.id))[0] is False
    assert len(await rows("SELECT * FROM exchange_arming")) == 2


async def test_a_transfer_is_capital_never_profit_or_loss(world: World) -> None:
    account = await live_account(world)
    orders = repository(world)
    await orders.day_start(account.id, NOW.date(), D(100))
    later = int((datetime.now(UTC) + timedelta(minutes=1)).timestamp() * 1000)
    moved = [
        {"tranId": 1, "income": "50", "asset": "USDT", "time": later},
        {"tranId": 2, "income": "-20", "asset": "USDT", "time": later + 1},
        {"tranId": 3, "income": "9", "asset": "BNB", "time": later + 2},  # Not USDT.
    ]
    assert await orders.store_transfers(account.id, moved) == 3
    assert await orders.store_transfers(account.id, moved) == 0, "Binance's IDs keep each once"
    assert await orders.funded(account.id) == D(130)
    assert await orders.moved_today(account.id, NOW.date()) == D(30)


async def test_the_first_check_makes_the_account_from_the_wallet_and_leaves_the_owners_trade(
    world: World,
) -> None:
    exchange = FakeGateway(positions=[OWNER_ETH], equity="150", available="140")
    loop = trading(world, link(world, exchange))
    await loop._check_exchange(loop._exchanges[0], NOW)
    account = await world.records.find_account(EMAIL, LIVE.name)
    assert account is not None and account.starting_balance == D(150)
    assert account.profile.max_risk_fraction == D("0.01")
    assert account.profile.max_total_loss_fraction == D("0.2")
    assert exchange.calls == [], "the owner's position is never given a stop or closed"
    stored = await repository(world).status(account.id)
    assert stored is not None
    _, body = stored
    assert body["budget"]["capital"] == "150" and body["budget"]["equity"] == "150"
    assert [(p["symbol"], p["bot"]) for p in body["positions"]] == [("ETHUSDT", False)]
    assert body["live"]["armed"] is False and body["live"]["problems"] == []
    assert body["live"]["ip_restricted"] is True


async def test_an_empty_futures_wallet_makes_no_account_until_the_owner_funds_it(
    world: World,
) -> None:
    exchange = FakeGateway(equity="0", available="0")
    live = link(world, exchange)
    loop = trading(world, live)
    await loop._check_exchange(live, NOW)
    assert await world.records.find_account(EMAIL, LIVE.name) is None
    exchange._equity = "100"
    await loop._check_exchange(live, NOW + timedelta(minutes=1))
    account = await world.records.find_account(EMAIL, LIVE.name)
    assert account is not None and account.starting_balance == D(100)


class Refused(FakeGateway):
    """A real account whose key Binance refuses, such as one without futures permission."""

    async def account(self) -> dict[str, Any]:
        raise BinanceError(401, -2015, "Invalid API-key, IP, or permissions for action.")


async def test_a_refused_key_never_stops_the_worker(world: World) -> None:
    """Regression: making the real account reads Binance before the minute check's guard. A
    refusal there escaped the handler, which would stop the worker for every account."""
    live = link(world, Refused())
    loop = trading(world, live)
    await loop._check_exchange(live, NOW)  # Logged as exchange_check_failed, not raised.
    assert await world.records.find_account(EMAIL, LIVE.name) is None


async def test_a_problem_is_checked_again_within_minutes_and_a_good_key_hourly() -> None:
    """Not on the database: once the owner fixes the key on Binance, trading resumes within
    about five minutes, not an hour."""
    answers = [
        AccountCheck(("the key can withdraw: turn it off",)),
        AccountCheck(()),
        AccountCheck(()),
    ]
    asked: list[int] = []

    async def check() -> AccountCheck:
        asked.append(1)
        return answers.pop(0)

    clock = FixedClock(NOW)
    live = ExchangeLink(LIVE, FuturesTrader(FakeGateway(), own_only=True), None, check)  # type: ignore[arg-type]
    loop = TradingLoop(None, None, None, EMAIL, 1, {}, clock, exchanges=[live])  # type: ignore[arg-type]
    await loop._health(live)
    assert live.health is not None and live.health.problems
    clock.advance(4 * 60)
    await loop._health(live)
    assert len(asked) == 1, "not yet"
    clock.advance(60)
    await loop._health(live)
    assert live.health.problems == () and len(asked) == 2
    clock.advance(30 * 60)
    await loop._health(live)
    assert len(asked) == 2, "a good key is checked hourly"
    clock.advance(30 * 60)
    await loop._health(live)
    assert len(asked) == 3


async def test_a_trade_closed_in_the_binance_app_is_seen_to_end(world: World) -> None:
    exchange = FakeGateway(equity="150")
    live = link(world, exchange)
    loop = trading(world, live)
    await loop._check_exchange(live, NOW)
    account = await world.records.find_account(EMAIL, LIVE.name)
    assert account is not None
    await bot_entry(world, account)
    # The owner closed it in the app: the coin is flat, and the bot's stop is left over.
    exchange._algo = [
        {"symbol": world.instrument.symbol, "orderType": "STOP_MARKET", "algoId": 9,
         "clientAlgoId": "ati-x-stop"},
    ]  # fmt: skip
    await loop._check_exchange(live, NOW + timedelta(minutes=1))
    assert ("cancel one", 9) in exchange.calls, "its leftover stop goes"
    assert await rows("SELECT * FROM exchange_trade_ends") == [], "flat once is not enough"
    await loop._check_exchange(live, NOW + timedelta(minutes=2))
    [ended] = await rows("SELECT trade_key, how FROM exchange_trade_ends")
    assert (ended["trade_key"], ended["how"]) == ("sol-trade", "flat_on_binance")
    assert await repository(world).open_trades(account.id) == {}


async def test_one_empty_reply_from_binance_never_hands_the_bots_position_to_the_owner(
    world: World,
) -> None:
    """The position is missing from one reply, then back. The trade is still the bot's, so the
    stop that went with the odd reply is put back at once."""
    symbol = world.instrument.symbol
    held = {"symbol": symbol, "positionAmt": "0.5", "entryPrice": "100", "notional": "50"}
    exchange = FakeGateway(equity="150")
    account = await live_account(world)
    await bot_entry(world, account)
    live = link(world, exchange)
    loop = trading(world, live)
    await loop._check_exchange(live, NOW)  # Binance reports no position this once.
    exchange._positions = [held]
    await loop._check_exchange(live, NOW + timedelta(minutes=1))
    assert await rows("SELECT * FROM exchange_trade_ends") == []
    assert ("STOP_MARKET", symbol, "SELL", D("98"), None) in exchange.calls
    assert symbol in await repository(world).open_trades(account.id)


async def test_a_bot_trade_the_owner_protects_in_the_app_stays_open(world: World) -> None:
    """Regression, 2026-11-14 02:11 UTC: the owner changed the real SOL short's stop in the
    Binance app, and the bot closed the trade at market. Now the owner's stop is kept (D066)."""
    symbol = world.instrument.symbol
    held = {"symbol": symbol, "positionAmt": "0.5", "entryPrice": "100", "notional": "50"}
    owners = {
        "symbol": symbol, "orderType": "STOP_MARKET", "algoId": 9, "clientAlgoId": "aos_x",
        "side": "SELL", "closePosition": True, "triggerPrice": "101",
    }  # fmt: skip
    exchange = FakeGateway(positions=[held], algo=[owners], equity="150")
    account = await live_account(world)
    await bot_entry(world, account)
    live = link(world, exchange)
    loop = trading(world, live)
    await loop._check_exchange(live, NOW)
    assert exchange.calls == [], "nothing restored, nothing closed"
    assert symbol in await repository(world).open_trades(account.id)


async def test_the_minute_check_locks_one_r_on_a_real_trade_one_and_a_half_r_up(
    world: World,
) -> None:
    """D066: the plan's long filled at 100 with its stop at 98, so 1R is 2. At a mark of 103 the
    minute check moves the stop to 102, and the minute check after reads 102 as the stop."""
    symbol = world.instrument.symbol
    account = await live_account(world)
    exchange = FakeGateway(filled=None, equity="150", available="150")
    setup = await plan_setup(world, TREND, "98.00")
    [outcome] = await world.signals.run_exchange_plan(
        world.provider_id, NOW, account, [setup], FuturesTrader(exchange, own_only=True),
        repository(world), live=True,
    )  # fmt: skip
    assert outcome.approved, outcome.reasons
    [stop_id] = await rows("SELECT client_id FROM exchange_orders WHERE kind = 'stop'")
    exchange._positions = [
        {"symbol": symbol, "positionAmt": "0.75", "entryPrice": "100", "notional": "77.25",
         "markPrice": "103"},
    ]  # fmt: skip
    exchange._algo = [
        {"symbol": symbol, "orderType": "STOP_MARKET", "algoId": 8, "side": "SELL",
         "closePosition": True, "triggerPrice": "98.00", "clientAlgoId": stop_id["client_id"]},
    ]  # fmt: skip
    exchange.calls.clear()
    live = link(world, exchange)
    await trading(world, live)._check_exchange(live, NOW)
    moves = [call for call in exchange.calls if call[0] in ("cancel one", "STOP_MARKET")]
    assert moves == [("cancel one", 8), ("STOP_MARKET", symbol, "SELL", D("102.00"), None)]
    [(stop, _)] = (await repository(world).open_trades(account.id)).values()
    assert stop == D("102.00")


async def risk_beside_an_eth_short(world: World, algo: list[dict[str, Any]]) -> Any:
    """The plan's risk row for a new trend trade beside the bot's ETH short. The short entered at
    3000 with its first stop at 3300, which was then locked at 2700. Whatever the short could
    lose is taken from the 4.5 USDT open-risk cap of the 150 USDT."""
    account = await live_account(world)
    orders = repository(world)
    eth = OrderRecord("ETHUSDT", "entry", "ati-e-entry", {"type": "MARKET"}, {"orderId": 2})
    await orders.record(account.id, None, eth, trade_key="eth-trade", stop_price=D("3300"))
    lock = OrderRecord("ETHUSDT", "stop", "ati-e-lock", {"type": "STOP_MARKET"}, {"algoId": 3})
    await orders.record(account.id, None, lock, trade_key="eth-trade", stop_price=D("2700"))
    short = {
        "symbol": "ETHUSDT",
        "positionAmt": "-0.0133",
        "entryPrice": "3000",
        "notional": "39.9",
    }
    exchange = FakeGateway(filled=None, positions=[short], algo=algo, equity="150", available="150")
    await world.signals.run_exchange_plan(
        world.provider_id, NOW, account, [await plan_setup(world, TREND, "98.00")],
        FuturesTrader(exchange, own_only=True), orders, live=True,
    )  # fmt: skip
    [row] = await rows("SELECT decision, rejection_codes, max_account_risk FROM risk_assessments")
    return row


async def test_a_stop_locked_past_the_entry_still_counts_its_first_risk(world: World) -> None:
    """D067. The lock at 2700 protects the short, but a gap can pass a stop. So the short still
    counts what it risked at its first stop, 3.99 USDT of the cap, and the next trade gets 0.51
    at most. Under D066 the lock counted as no risk, and the next trade got its full 1.5."""
    row = await risk_beside_an_eth_short(world, [])
    assert row["decision"] == "APPROVED" and row["max_account_risk"] <= D("0.51")


async def test_a_wider_stop_binance_holds_counts_in_full(world: World) -> None:
    """The owner moved that short's stop out to 3400 in the app, so it can lose 5.32 USDT, more
    than the whole 4.5 USDT cap."""
    owners = {
        "symbol": "ETHUSDT", "orderType": "STOP_MARKET", "algoId": 5, "clientAlgoId": "aos_1",
        "side": "BUY", "closePosition": True, "triggerPrice": "3400",
    }  # fmt: skip
    row = await risk_beside_an_eth_short(world, [owners])
    assert row["decision"] == "REJECTED" and "OPEN_RISK_FULL" in row["rejection_codes"]


async def test_a_trade_is_shrunk_to_the_room_left_on_its_side(world: World) -> None:
    """D072: with longs capped at 60% of the 150 USDT, the bot's ETH long worth 60 leaves 30
    for the next long, so the trend trade is shrunk to fit rather than refused."""
    capped = LIVE.profile.model_copy(update={"max_side_exposure_fraction": D("0.6")})
    account = await world.records.ensure_account(EMAIL, LIVE.name, D(150), capped, mode=LIVE.mode)
    assert account is not None
    orders = repository(world)
    eth = OrderRecord("ETHUSDT", "entry", "ati-e-entry", {"type": "MARKET"}, {"orderId": 2})
    await orders.record(account.id, None, eth, trade_key="eth-trade", stop_price=D("2990"))
    long = {"symbol": "ETHUSDT", "positionAmt": "0.02", "entryPrice": "3000", "notional": "60"}
    exchange = FakeGateway(filled=None, positions=[long], equity="150", available="150")
    [outcome] = await world.signals.run_exchange_plan(
        world.provider_id, NOW, account, [await plan_setup(world, TREND, "98.00")],
        FuturesTrader(exchange, own_only=True), orders, live=True,
    )  # fmt: skip
    assert outcome.approved, outcome.reasons
    [row] = await rows("SELECT notional FROM risk_assessments")
    assert D(25) < row["notional"] <= D(30)


async def test_the_dashboards_close_closes_the_bots_trade_and_frees_its_coin(world: World) -> None:
    symbol = world.instrument.symbol
    held = {"symbol": symbol, "positionAmt": "0.5", "entryPrice": "100", "notional": "50"}
    stop = {"symbol": symbol, "orderType": "STOP_MARKET", "algoId": 9}
    exchange = FakeGateway(positions=[held], algo=[{**stop, "clientAlgoId": "ati-x-stop"}])
    account = await live_account(world)
    await bot_entry(world, account)
    live = link(world, exchange)
    loop = trading(world, live)
    await loop._check_exchange(live, NOW)
    assert exchange.calls == [], "the bot's position already has its stop"
    orders = repository(world)
    request = await orders.request_close(account.id, symbol, EMAIL)
    await loop.run_closes()
    assert exchange.calls == [("market", symbol, "SELL", D("0.5"), True), ("cancel one", 9)]
    [done] = await orders.closes(account.id)
    assert done.id == request.id and done.outcome == "closed"
    [ended] = await rows("SELECT how FROM exchange_trade_ends")
    assert ended["how"] == "closed_from_dashboard"
    assert await orders.open_trades(account.id) == {}
    closes = await rows("SELECT client_id FROM exchange_orders WHERE kind = 'close'")
    assert len(closes) == 2, "the close and the cancel are stored with every other order"


async def test_the_dashboard_cannot_close_a_position_that_is_not_the_bots(world: World) -> None:
    exchange = FakeGateway(positions=[OWNER_ETH], equity="150")
    live = link(world, exchange)
    loop = trading(world, live)
    await loop._check_exchange(live, NOW)
    account = await world.records.find_account(EMAIL, LIVE.name)
    assert account is not None
    await repository(world).request_close(account.id, "ETHUSDT", EMAIL)
    await loop.run_closes()
    [done] = await repository(world).closes(account.id)
    assert done.outcome == "not_the_bots" and exchange.calls == []


async def test_the_real_account_trades_only_once_armed_and_checked(world: World) -> None:
    exchange = FakeGateway(filled=None, equity="150", available="150")
    live = link(world, exchange)
    loop = trading(world, live)
    await loop._check_exchange(live, NOW)
    setups = [await plan_setup(world, strategy, "98.00") for strategy in (BASELINE, PATTERN, TREND)]
    await loop._plan_exchange(live, world.provider_id, NOW, setups)
    assert not any(call[0] == "market" for call in exchange.calls), "not armed"
    account = await world.records.find_account(EMAIL, LIVE.name)
    assert account is not None
    await repository(world).set_armed(account.id, True, EMAIL)
    refused = link(world, exchange, problems=("the key can withdraw: turn it off",))
    refused_loop = trading(world, refused)
    await refused_loop._check_exchange(refused, NOW)
    await refused_loop._plan_exchange(refused, world.provider_id, NOW, setups)
    assert not any(call[0] == "market" for call in exchange.calls), "a refused key trades nothing"
    await loop._plan_exchange(live, world.provider_id, NOW, setups)
    assert sum(call[0] == "market" for call in exchange.calls) == 1
    [risk] = await rows("SELECT max_account_risk FROM risk_assessments WHERE decision = 'APPROVED'")
    assert D("1.47") < risk["max_account_risk"] <= D("1.5"), "1% of the 150 USDT in the wallet"


async def test_a_transfer_in_today_is_not_taken_for_a_days_profit(world: World) -> None:
    """The day began at 100 and the owner moved 50 in. Counted as profit, the +3% daily stop
    would refuse every trade; as capital, the day is flat and the trade goes ahead."""
    account = await live_account(world, D(100))
    orders = repository(world)
    await orders.day_start(account.id, NOW.date(), D(100))
    later = int((datetime.now(UTC) + timedelta(minutes=1)).timestamp() * 1000)
    await orders.store_transfers(
        account.id, [{"tranId": 7, "income": "50", "asset": "USDT", "time": later}]
    )
    setup = await plan_setup(world, TREND, "98.00")
    exchange = FakeGateway(filled=None, equity="150", available="150")
    [outcome] = await world.signals.run_exchange_plan(
        world.provider_id, NOW, account, [setup], FuturesTrader(exchange, own_only=True), orders,
        live=True,
    )  # fmt: skip
    assert outcome.approved, outcome.reasons


async def test_the_owners_own_position_counts_at_its_whole_value(world: World) -> None:
    """The bot knows no stop for it, so its 1,500 USDT fills every bit of the 3% open risk."""
    account = await live_account(world)
    setup = await plan_setup(world, TREND, "98.00")
    exchange = FakeGateway(filled=None, positions=[OWNER_ETH], equity="150", available="150")
    [outcome] = await world.signals.run_exchange_plan(
        world.provider_id, NOW, account, [setup], FuturesTrader(exchange, own_only=True),
        repository(world), live=True,
    )  # fmt: skip
    assert not outcome.approved
    [row] = await rows("SELECT rejection_codes FROM risk_assessments")
    assert "OPEN_RISK_FULL" in row["rejection_codes"]
    assert not any(call[0] == "market" for call in exchange.calls)


async def test_demo_trading_opens_nothing_while_switched_off(world: World) -> None:
    """D064: the switch stops new demo trades; turned back on, the plan trades again."""
    exchange = FakeGateway(filled=None)
    demo = ExchangeLink(DEMO, FuturesTrader(exchange), repository(world))
    loop = trading(world, demo)
    account = await world.records.ensure_account(
        EMAIL, DEMO.name, DEMO.budget, DEMO.profile, mode=DEMO.mode
    )
    assert account is not None
    await repository(world).set_armed(account.id, False, EMAIL, "test")
    setups = [await plan_setup(world, TREND, "98.00")]
    await loop._plan_exchange(demo, world.provider_id, NOW, setups)
    assert exchange.calls == [], "switched off"
    await repository(world).set_armed(account.id, True, EMAIL, "test")
    await loop._plan_exchange(demo, world.provider_id, NOW, setups)
    assert any(call[0] == "market" for call in exchange.calls)
