"""The real account (D060): the bot touches only its own orders and trades, and closes on request.

Everything runs against a fake exchange. Nothing here reaches Binance.
"""

from decimal import Decimal
from typing import Any

from tests.exchange_fakes import FakeGateway
from trading_intel.domain.signals import Side
from trading_intel.execution.binance_futures import BinanceError
from trading_intel.execution.orders import client_id
from trading_intel.execution.trader import (
    Budget,
    ExchangeView,
    FuturesTrader,
    Position,
    describe,
    held_stops,
)

D = Decimal
BOT_STOP = {
    "symbol": "SOLUSDT",
    "orderType": "STOP_MARKET",
    "algoId": 11,
    "clientAlgoId": "ati-a-stop",
}
BOT_TARGET = {
    "symbol": "SOLUSDT",
    "orderType": "TAKE_PROFIT_MARKET",
    "algoId": 12,
    "clientAlgoId": "ati-a-tp1",
    "triggerPrice": "110",
    "quantity": "0.5",
}
# Orders the owner placed in the Binance app carry Binance's own client IDs.
OWNER_STOP = {
    "symbol": "ETHUSDT",
    "orderType": "STOP_MARKET",
    "algoId": 21,
    "clientAlgoId": "ios_x",
}


def position(symbol: str, amount: str) -> dict[str, Any]:
    return {"symbol": symbol, "positionAmt": amount, "entryPrice": "100", "notional": "1000"}


def resting(symbol: str, client: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "type": "LIMIT",
        "side": "BUY",
        "price": "83.2",
        "origQty": "0.5",
        "executedQty": "0",
        "reduceOnly": False,
        "clientOrderId": client,
    }


def live(exchange: FakeGateway) -> FuturesTrader:
    return FuturesTrader(exchange, own_only=True)


async def test_the_owners_own_position_is_never_given_a_stop_or_closed() -> None:
    """On demo trading such a position is closed (no known stop). On the real account it is the
    owner's, so the minute check leaves it alone."""
    exchange = FakeGateway(positions=[position("ETHUSDT", "-0.5")])
    assert await live(exchange).reconcile({}) == []
    assert exchange.calls == []


async def test_the_bots_position_without_its_stop_gets_it_back() -> None:
    exchange = FakeGateway(positions=[position("SOLUSDT", "2")], algo=[OWNER_STOP])
    await live(exchange).reconcile({"SOLUSDT": (D("92"), "sol-key")})
    assert exchange.calls == [("STOP_MARKET", "SOLUSDT", "SELL", D("92"), None)]


async def test_an_owners_stop_for_part_of_the_bots_position_does_not_protect_it() -> None:
    part = {**OWNER_STOP, "symbol": "SOLUSDT", "side": "SELL", "quantity": "1", "reduceOnly": True}
    exchange = FakeGateway(positions=[position("SOLUSDT", "2")], algo=[part])
    await live(exchange).reconcile({"SOLUSDT": (D("92"), "sol-key")})
    assert ("STOP_MARKET", "SOLUSDT", "SELL", D("92"), None) in exchange.calls
    assert not any(call[0].startswith("cancel") for call in exchange.calls)


# The owner's whole-position stop on the bot's SOL long, as the Binance app sets one.
OWNERS_SOL_STOP = {
    **OWNER_STOP,
    "symbol": "SOLUSDT",
    "side": "SELL",
    "closePosition": True,
    "triggerPrice": "101",
    "clientAlgoId": "aos_x",
}
STOP_STANDS = BinanceError(
    400, -4130, "An open stop or take profit order with GTE and closePosition in the direction "
    "is existing."
)  # fmt: skip


async def test_a_bot_trade_the_owner_protects_in_the_app_keeps_that_stop_and_stays_open() -> None:
    """D066: the owner moved the bot's stop in the Binance app. The bot keeps the owner's stop
    and the trade, and sends nothing."""
    exchange = FakeGateway(positions=[position("SOLUSDT", "2")], algo=[OWNERS_SOL_STOP])
    assert await live(exchange).reconcile({"SOLUSDT": (D("92"), "sol-key")}) == []
    assert exchange.calls == []


async def test_a_stop_refused_because_one_already_stands_closes_nothing() -> None:
    """Regression, 2026-11-14 02:11 UTC: the real SOL short had no stop the bot could see, its
    stop was refused with -4130 because a whole-position stop stood, and the bot closed the
    trade at market. Binance itself says a stop protects it, so the trade stays."""
    exchange = FakeGateway(
        positions=[position("SOLUSDT", "-0.18")], fails={"STOP_MARKET": STOP_STANDS}
    )
    [refused] = await live(exchange).reconcile({"SOLUSDT": (D("87.26"), "sol-key")})
    assert refused.code == -4130
    assert exchange.calls == [("STOP_MARKET", "SOLUSDT", "BUY", D("87.26"), None)]


async def test_a_stop_move_leaves_the_owners_own_stop_alone() -> None:
    exchange = FakeGateway(positions=[position("SOLUSDT", "2")], algo=[OWNERS_SOL_STOP])
    move = await live(exchange).move_stop("SOLUSDT", D("103"), "sol-key:lock:1")
    assert not move.moved and move.held == (D("101"), "aos_x")
    assert exchange.calls == [] and move.records == []


async def test_a_moved_stop_refused_because_one_already_stands_closes_nothing() -> None:
    exchange = FakeGateway(
        positions=[position("SOLUSDT", "2")],
        algo=[{**BOT_STOP, "triggerPrice": "92"}],
        fails={"STOP_MARKET": STOP_STANDS},
    )
    move = await live(exchange).move_stop("SOLUSDT", D("103"), "sol-key:lock:1")
    assert not move.moved and move.held is None
    assert not any(call[0] == "market" for call in exchange.calls)


def test_the_stop_binance_holds_is_the_tightest_that_closes_the_whole_position() -> None:
    sol = Position("SOLUSDT", D(2), D(100), D(200))
    eth = Position("ETHUSDT", D("-0.5"), D(3000), D(1500))
    orders = [
        {**OWNERS_SOL_STOP, "triggerPrice": "101"},
        {**BOT_STOP, "side": "SELL", "closePosition": "true", "triggerPrice": "92"},
        {**BOT_STOP, "side": "SELL", "quantity": "1", "triggerPrice": "105"},  # Half of it.
        {**BOT_STOP, "side": "BUY", "closePosition": True, "triggerPrice": "106"},  # Opens.
        {**OWNER_STOP, "side": "BUY", "quantity": "0.5", "triggerPrice": "2900"},
        {**BOT_TARGET, "side": "SELL", "closePosition": True},
    ]
    assert held_stops({"SOLUSDT": sol, "ETHUSDT": eth}, orders) == {
        "SOLUSDT": D("101"),
        "ETHUSDT": D("2900"),
    }


async def test_only_the_bots_leftover_orders_are_cancelled_one_by_one() -> None:
    """A coin the bot no longer holds keeps none of its orders; the owner's stay, and nothing is
    cancelled coin-wide."""
    exchange = FakeGateway(algo=[BOT_STOP, BOT_TARGET, OWNER_STOP])
    records = await live(exchange).reconcile({})
    assert exchange.calls == [("cancel one", 11), ("cancel one", 12)]
    assert {r.symbol for r in records} == {"SOLUSDT"}


async def test_the_bots_orders_go_when_the_coins_position_is_the_owners() -> None:
    """The bot's trade ended, then the owner opened a position on the same coin. The bot's
    reduce-only stop must not close the owner's position."""
    exchange = FakeGateway(positions=[position("SOLUSDT", "1")], algo=[BOT_STOP])
    await live(exchange).reconcile({})
    assert exchange.calls == [("cancel one", 11)]


async def test_a_waiting_entry_without_a_stop_is_cancelled_only_if_it_is_the_bots() -> None:
    exchange = FakeGateway(entries=[resting("SOLUSDT", "ati-w-entry"), resting("XRPUSDT", "web_1")])
    await live(exchange).reconcile({"SOLUSDT": (D("80"), "sol-key")})
    assert exchange.calls == [("cancel entry", "SOLUSDT", "ati-w-entry")]


async def test_a_trailing_stop_moves_only_the_bots_own_stop() -> None:
    owner_on_sol = {**OWNER_STOP, "symbol": "SOLUSDT", "triggerPrice": "70"}
    exchange = FakeGateway(
        positions=[position("SOLUSDT", "2")],
        algo=[owner_on_sol, {**BOT_STOP, "triggerPrice": "92"}],
    )
    move = await live(exchange).move_stop("SOLUSDT", D("94"), "sol-key:trail:1")
    assert move.moved
    assert exchange.calls == [("cancel one", 11), ("STOP_MARKET", "SOLUSDT", "SELL", D("94"), None)]


async def test_closing_from_the_dashboard_closes_at_market_then_cancels_the_bots_orders() -> None:
    exchange = FakeGateway(
        positions=[position("SOLUSDT", "-0.5")], algo=[BOT_STOP, BOT_TARGET, OWNER_STOP]
    )
    result = await live(exchange).close_trade("SOLUSDT", "dashboard:r1")
    assert result.outcome == "closed"
    assert exchange.calls == [
        ("market", "SOLUSDT", "BUY", D("0.5"), True),
        ("cancel one", 11),
        ("cancel one", 12),
    ]
    close = result.records[0]
    assert close.kind == "close" and close.client_id == client_id("dashboard:r1:close", "close")
    assert close.request == {"side": "BUY", "type": "MARKET", "quantity": "0.5", "reduceOnly": True}


async def test_a_refused_close_keeps_the_stop_and_targets() -> None:
    refused = BinanceError(400, -2022, "ReduceOnly Order is rejected.")
    exchange = FakeGateway(
        positions=[position("SOLUSDT", "-0.5")], algo=[BOT_STOP], fails={"close": refused}
    )
    result = await live(exchange).close_trade("SOLUSDT", "dashboard:r2")
    assert result.outcome == "failed" and "ReduceOnly" in (result.detail or "")
    assert not any(call[0].startswith("cancel") for call in exchange.calls)


async def test_closing_a_waiting_entry_cancels_it_first() -> None:
    exchange = FakeGateway(entries=[resting("SOLUSDT", "ati-w-entry")], algo=[BOT_STOP])
    result = await live(exchange).close_trade("SOLUSDT", "dashboard:r3")
    assert result.outcome == "closed"
    assert exchange.calls == [("cancel entry", "SOLUSDT", "ati-w-entry"), ("cancel one", 11)]


async def test_closing_a_coin_with_nothing_open_sends_nothing() -> None:
    exchange = FakeGateway(entries=[resting("SOLUSDT", "web_1")])
    result = await live(exchange).close_trade("SOLUSDT", "dashboard:r4")
    assert result.outcome == "nothing_open" and exchange.calls == []


async def test_closing_on_demo_cancels_every_order_on_the_coin() -> None:
    exchange = FakeGateway(positions=[position("SOLUSDT", "2")], algo=[BOT_STOP])
    result = await FuturesTrader(exchange).close_trade("SOLUSDT", "dashboard:r5")
    assert result.outcome == "closed"
    assert exchange.calls == [("market", "SOLUSDT", "SELL", D("2"), True), ("cancel", "SOLUSDT")]


async def test_the_kill_switch_closes_only_the_bots_trades_and_cancels_only_its_orders() -> None:
    exchange = FakeGateway(
        positions=[position("SOLUSDT", "2"), position("ETHUSDT", "-0.5")],
        algo=[BOT_STOP, OWNER_STOP],
        entries=[resting("XRPUSDT", "ati-x-entry"), resting("BNBUSDT", "web_2")],
    )
    await live(exchange).flatten_all({"SOLUSDT"})
    assert exchange.calls == [
        ("cancel entry", "XRPUSDT", "ati-x-entry"),
        ("market", "SOLUSDT", "SELL", D("2"), True),
        ("cancel one", 11),
    ]


async def test_demos_kill_switch_still_clears_the_whole_account() -> None:
    exchange = FakeGateway(positions=[position("ETHUSDT", "-0.5")], algo=[OWNER_STOP])
    await FuturesTrader(exchange).flatten_all()
    assert exchange.calls == [("cancel", "ETHUSDT"), ("market", "ETHUSDT", "BUY", D("0.5"), True)]


def test_the_whole_wallet_is_the_budget_and_a_transfer_is_never_a_profit() -> None:
    view = ExchangeView(equity=D(150), available=D(140), positions={})
    # The day began at 100, then the owner moved 50 USDT in: the day's result is zero.
    budget = Budget.wallet(view, day_start=D(100), moved_today=D(50))
    assert budget.equity == D(150) and budget.available == D(140)
    assert budget.day_start_equity == D(150)
    out = Budget.wallet(ExchangeView(equity=D(60), available=D(60), positions={}), D(100), D(-40))
    assert out.day_start_equity == D(60), "moving 40 out is not a loss either"


def test_the_dashboard_marks_the_owners_positions_and_orders() -> None:
    sol = Position("SOLUSDT", D(2), D(100), D(200))
    eth = Position("ETHUSDT", D("-0.5"), D(3000), D(1500))
    view = ExchangeView(equity=D(150), available=D(100), positions={"SOLUSDT": sol, "ETHUSDT": eth})
    budget = Budget.wallet(view, D(150), D(0))
    body = describe(view, [BOT_STOP, OWNER_STOP], budget, D(150), trades={"SOLUSDT"})
    assert {p["symbol"]: p["bot"] for p in body["positions"]} == {"ETHUSDT": False, "SOLUSDT": True}
    assert {o["symbol"]: o["bot"] for o in body["orders"]} == {"ETHUSDT": False, "SOLUSDT": True}
    demo = describe(view, [OWNER_STOP], budget, D(100))
    assert all(p["bot"] for p in demo["positions"]) and all(o["bot"] for o in demo["orders"])


def test_a_waiting_entry_knows_whether_the_bot_placed_it() -> None:
    from trading_intel.execution.trader import PendingEntry

    assert PendingEntry("SOLUSDT", Side.LONG, D(1), D(1), "ati-x-entry").by_bot
    assert not PendingEntry("SOLUSDT", Side.LONG, D(1), D(1), "web_123").by_bot
