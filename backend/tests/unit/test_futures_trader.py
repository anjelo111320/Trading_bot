"""Opening, protecting and flattening Binance demo trades, against a fake exchange."""

import re
from decimal import Decimal
from typing import Any

import httpx

from tests.exchange_fakes import FakeGateway
from trading_intel.domain.signals import Side
from trading_intel.execution.binance_futures import BinanceError
from trading_intel.execution.orders import TradePlan, client_id, price_limits, target_sizes
from trading_intel.execution.trader import Budget, ExchangeView, FuturesTrader, Position

D = Decimal
ALLOCATION = (D("0.5"), D("0.3"), D("0.2"))


def plan(**changes: Any) -> TradePlan:
    values: dict[str, Any] = {
        "key": "account:1:LONG:15m:100:2",
        "symbol": "BTCUSDT",
        "side": Side.LONG,
        "leverage": 1,
        "quantity": D("0.010"),
        "stop": D("95"),
        "targets": (D("110"), D("115"), D("120")),
        "allocation": ALLOCATION,
        "lot_step": D("0.001"),
        "min_qty": D("0.001"),
    }
    return TradePlan(**{**values, **changes})


def position(symbol: str, amount: str) -> dict[str, Any]:
    return {"symbol": symbol, "positionAmt": amount, "entryPrice": "100", "notional": "1000"}


def test_order_ids_are_stable_short_and_in_binances_alphabet() -> None:
    first = client_id("account:1:LONG:15m:100:2", "entry")
    assert first == client_id("account:1:LONG:15m:100:2", "entry")
    assert first != client_id("account:1:LONG:15m:100:2", "stop")
    for kind in ("entry", "stop", "tp1", "close"):
        assert re.fullmatch(r"[\.A-Z\:/a-z0-9_-]{1,36}", client_id("k", kind))  # type: ignore[arg-type]


def test_targets_split_50_30_20_on_the_lot_step_with_the_remainder_last() -> None:
    assert target_sizes(D("0.010"), ALLOCATION, D("0.001"), D("0.001")) == (
        D("0.005"),
        D("0.003"),
        D("0.002"),
    )
    assert target_sizes(D("0.011"), ALLOCATION, D("0.001"), D("0.001")) == (
        D("0.005"),
        D("0.003"),
        D("0.003"),
    )
    # Shares below the minimum quantity move to the next target, so each order is valid.
    assert target_sizes(D("0.003"), ALLOCATION, D("0.001"), D("0.002")) == (D(0), D(0), D("0.003"))
    assert sum(target_sizes(D("7.37"), ALLOCATION, D("0.01"), D("0.01"))) == D("7.37")


async def test_a_trade_opens_isolated_then_gets_its_stop_then_its_targets() -> None:
    exchange = FakeGateway()
    result = await FuturesTrader(exchange).open_trade(plan(leverage=2))
    assert result.protected and result.filled == D("0.010")
    assert exchange.calls == [
        ("isolated", "BTCUSDT"),
        ("leverage", "BTCUSDT", 2),
        ("market", "BTCUSDT", "BUY", D("0.010"), False),
        ("STOP_MARKET", "BTCUSDT", "SELL", D("95"), None),
        ("TAKE_PROFIT_MARKET", "BTCUSDT", "SELL", D("110"), D("0.005")),
        ("TAKE_PROFIT_MARKET", "BTCUSDT", "SELL", D("115"), D("0.003")),
        ("TAKE_PROFIT_MARKET", "BTCUSDT", "SELL", D("120"), D("0.002")),
    ]
    assert [r.kind for r in result.records] == ["entry", "stop", "tp1", "tp2", "tp3"]


async def test_a_short_closes_with_buys() -> None:
    exchange = FakeGateway()
    await FuturesTrader(exchange).open_trade(
        plan(side=Side.SHORT, stop=D("105"), targets=(D("90"),), allocation=(D(1),))
    )
    assert exchange.calls[2] == ("market", "BTCUSDT", "SELL", D("0.010"), False)
    assert exchange.calls[3][:3] == ("STOP_MARKET", "BTCUSDT", "BUY")
    assert exchange.calls[4] == ("TAKE_PROFIT_MARKET", "BTCUSDT", "BUY", D("90"), D("0.010"))


def test_price_limits_come_from_binances_price_filter() -> None:
    raw = {"filters": [{"filterType": "PRICE_FILTER", "minPrice": "0.4200", "maxPrice": "6857"}]}
    assert price_limits(raw) == (D("0.42"), D(6857))
    assert price_limits({}) == (D(0), None), "rules without the filter limit nothing"


async def test_a_target_binance_cannot_hold_is_not_sent() -> None:
    """Regression: the daily trend's far cap on a SOL short was 0.01, below Binance's lowest
    price of 0.42, and was refused with -4013 (2026-11-11)."""
    exchange = FakeGateway()
    result = await FuturesTrader(exchange).open_trade(
        plan(
            side=Side.SHORT,
            stop=D("92.51"),
            targets=(D("0.01"),),
            allocation=(D(1),),
            min_price=D("0.42"),
            max_price=D(6857),
        )
    )
    assert result.protected
    assert [call[0] for call in exchange.calls][-1] == "STOP_MARKET"
    assert not any(call[0] == "TAKE_PROFIT_MARKET" for call in exchange.calls)
    capped = plan(targets=(D("110"), D("115"), D(7000)), max_price=D(6857))
    assert [order.kind for order in capped.target_orders(D("0.010"))] == ["tp1", "tp2"]


async def test_targets_follow_what_actually_filled() -> None:
    exchange = FakeGateway(filled="0.004")
    await FuturesTrader(exchange).open_trade(plan())
    sizes = [call[4] for call in exchange.calls if call[0] == "TAKE_PROFIT_MARKET"]
    assert sizes == [D("0.002"), D("0.001"), D("0.001")]


async def test_a_position_that_cannot_get_its_stop_is_closed_at_once() -> None:
    refused = BinanceError(400, -2021, "Order would immediately trigger.")
    exchange = FakeGateway(fails={"STOP_MARKET": refused})
    result = await FuturesTrader(exchange).open_trade(plan())
    assert not result.protected
    assert exchange.calls[-1] == ("market", "BTCUSDT", "SELL", D("0.010"), True)
    assert not any(call[0] == "TAKE_PROFIT_MARKET" for call in exchange.calls)
    assert [r.kind for r in result.records] == ["entry", "stop", "close"]
    assert result.records[1].error is not None


async def test_a_refused_entry_sends_nothing_else_and_no_reply_is_recorded_as_unknown() -> None:
    exchange = FakeGateway(fails={"entry": BinanceError(400, -2019, "Margin is insufficient.")})
    result = await FuturesTrader(exchange).open_trade(plan())
    assert result.filled == 0 and len(exchange.calls) == 3
    lost = FakeGateway(fails={"entry": httpx.ReadTimeout("slow")})
    result = await FuturesTrader(lost).open_trade(plan())
    assert result.records[-1].error == "no reply: ReadTimeout"


async def test_the_minute_check_cancels_orders_on_flat_coins_and_restores_a_missing_stop() -> None:
    exchange = FakeGateway(
        positions=[position("ETHUSDT", "-0.5"), position("SOLUSDT", "2")],
        algo=[
            {"symbol": "BTCUSDT", "orderType": "TAKE_PROFIT_MARKET"},
            {"symbol": "SOLUSDT", "orderType": "STOP_MARKET"},
        ],
    )
    records = await FuturesTrader(exchange).reconcile({"ETHUSDT": (D("3200"), "eth-key")})
    assert ("cancel", "BTCUSDT") in exchange.calls
    assert ("STOP_MARKET", "ETHUSDT", "BUY", D("3200"), None) in exchange.calls
    assert not any(call[1] == "SOLUSDT" for call in exchange.calls)  # Already protected.
    assert {r.symbol for r in records} == {"BTCUSDT", "ETHUSDT"}


async def test_a_position_with_no_known_stop_is_closed() -> None:
    exchange = FakeGateway(positions=[position("DOGEUSDT", "100")])
    await FuturesTrader(exchange).reconcile({})
    assert exchange.calls == [("market", "DOGEUSDT", "SELL", D("100"), True)]


def held_stop(trigger: str = "92.51") -> dict[str, Any]:
    return {
        "symbol": "SOLUSDT",
        "orderType": "STOP_MARKET",
        "algoId": 7,
        "clientAlgoId": "ati-old-stop",
        "triggerPrice": trigger,
    }


async def test_a_stop_moves_by_cancelling_the_old_one_then_placing_the_new() -> None:
    exchange = FakeGateway(positions=[position("SOLUSDT", "-0.1")], algo=[held_stop()])
    move = await FuturesTrader(exchange).move_stop("SOLUSDT", D("90.10"), "sol-key:trail:1")
    assert move.moved and move.held == (D("90.10"), client_id("sol-key:trail:1", "stop"))
    assert exchange.calls == [
        ("cancel one", 7),
        ("STOP_MARKET", "SOLUSDT", "BUY", D("90.10"), None),
    ]
    assert [(r.kind, r.request.get("cancel")) for r in move.records] == [
        ("stop", "algoOrder"),
        ("stop", None),
    ]


async def test_a_refused_new_stop_puts_the_old_one_back() -> None:
    refused = BinanceError(400, -2021, "Order would immediately trigger.")
    exchange = FakeGateway(
        positions=[position("SOLUSDT", "-0.1")],
        algo=[held_stop()],
        fails={"STOP_MARKET": [refused, None]},
    )
    move = await FuturesTrader(exchange).move_stop("SOLUSDT", D("90.10"), "sol-key:trail:1")
    assert not move.moved
    assert move.held == (D("92.51"), client_id("sol-key:trail:1:back", "stop"))
    assert exchange.calls[-1] == ("STOP_MARKET", "SOLUSDT", "BUY", D("92.51"), None)
    assert not any(call[0] == "market" for call in exchange.calls)


async def test_a_position_left_with_no_stop_at_all_is_closed() -> None:
    refused = BinanceError(400, -2021, "Order would immediately trigger.")
    exchange = FakeGateway(
        positions=[position("SOLUSDT", "-0.1")], algo=[held_stop()], fails={"STOP_MARKET": refused}
    )
    move = await FuturesTrader(exchange).move_stop("SOLUSDT", D("90.10"), "sol-key:trail:1")
    assert move.held is None and not move.moved
    assert exchange.calls[-1] == ("market", "SOLUSDT", "BUY", D("0.1"), True)


async def test_a_stop_whose_cancel_fails_is_left_as_it_is() -> None:
    exchange = FakeGateway(
        positions=[position("SOLUSDT", "-0.1")],
        algo=[held_stop()],
        fails={"cancel one": BinanceError(400, -2011, "Unknown order sent.")},
    )
    move = await FuturesTrader(exchange).move_stop("SOLUSDT", D("90.10"), "sol-key:trail:1")
    assert not move.moved and exchange.calls == [("cancel one", 7)]
    assert move.records[0].error is not None
    flat = FakeGateway(algo=[held_stop()])
    assert not (await FuturesTrader(flat).move_stop("SOLUSDT", D("90.10"), "k")).records
    assert flat.calls == [], "a coin with no position has no stop to move"


async def test_the_kill_switch_cancels_everything_then_closes_every_position() -> None:
    exchange = FakeGateway(
        positions=[position("ETHUSDT", "-0.5")],
        algo=[{"symbol": "BTCUSDT", "orderType": "STOP_MARKET"}],
    )
    await FuturesTrader(exchange).flatten_all()
    assert exchange.calls == [
        ("cancel", "BTCUSDT"),
        ("cancel", "ETHUSDT"),
        ("market", "ETHUSDT", "BUY", D("0.5"), True),
    ]


async def test_the_view_reads_equity_margin_and_open_positions_only() -> None:
    exchange = FakeGateway(positions=[position("ETHUSDT", "-0.5"), position("BTCUSDT", "0")])
    view = await FuturesTrader(exchange).view()
    assert view.equity == D(5000) and view.available == D(4800)
    assert list(view.positions) == ["ETHUSDT"]
    assert view.positions["ETHUSDT"].side is Side.SHORT


def test_the_budget_is_the_capital_plus_the_bots_own_profit_and_loss() -> None:
    held = Position("ETHUSDT", D("-0.01"), D(3000), D(30), margin=D(30))
    view = ExchangeView(equity=D(5010), available=D(4970), positions={"ETHUSDT": held})
    budget = Budget.of(view, capital=D(100), baseline=D(5000), day_start=D(4990))
    assert budget.equity == D(110)  # 100 plus the 10 Binance's equity gained since the start.
    assert budget.day_start_equity == D(90)
    assert budget.available == D(80)  # 110 less the 30 the open position holds.
    poor = ExchangeView(equity=D(5010), available=D(20), positions={})
    assert Budget.of(poor, D(100), D(5000), D(5000)).available == D(20), "Binance's own limit"


UNTIL = 1_800_007_200_000


def resting(symbol: str = "SOLUSDT", side: str = "BUY", filled: str = "0") -> dict[str, Any]:
    """A limit entry waiting in Binance's book, as `openOrders` reports it."""
    return {
        "symbol": symbol,
        "type": "LIMIT",
        "side": side,
        "price": "83.2",
        "origQty": "0.5",
        "executedQty": filled,
        "reduceOnly": False,
        "clientOrderId": "ati-wait-entry",
    }


async def test_a_limit_entry_waits_with_its_stop_and_targets_already_on_binance() -> None:
    """D054: the stop is reduce-only for the planned size, so a fill is protected at once."""
    exchange = FakeGateway()
    result = await FuturesTrader(exchange).open_trade(plan(limit=D("100"), good_till_ms=UNTIL))
    assert result.protected and result.waiting and result.filled == 0
    assert exchange.calls == [
        ("isolated", "BTCUSDT"),
        ("leverage", "BTCUSDT", 1),
        ("limit", "BTCUSDT", "BUY", D("0.010"), D("100"), UNTIL),
        ("STOP_MARKET", "BTCUSDT", "SELL", D("95"), D("0.010")),
        ("TAKE_PROFIT_MARKET", "BTCUSDT", "SELL", D("110"), D("0.005")),
        ("TAKE_PROFIT_MARKET", "BTCUSDT", "SELL", D("115"), D("0.003")),
        ("TAKE_PROFIT_MARKET", "BTCUSDT", "SELL", D("120"), D("0.002")),
    ]
    entry, stop = result.records[0], result.records[1]
    assert entry.request["type"] == "LIMIT" and entry.request["goodTillDate"] == UNTIL
    assert stop.request["reduceOnly"] is True and "closePosition" not in stop.request


async def test_a_limit_entry_whose_stop_is_refused_is_cancelled() -> None:
    refused = BinanceError(400, -4509, "Binance 400 -4509: GTE can only be used with positions")
    exchange = FakeGateway(fails={"STOP_MARKET": refused})
    result = await FuturesTrader(exchange).open_trade(plan(limit=D("100"), good_till_ms=UNTIL))
    assert not result.protected and not result.waiting
    assert exchange.calls[-1] == ("cancel entry", "BTCUSDT", plan().entry_id)
    assert not any(call[0] == "TAKE_PROFIT_MARKET" for call in exchange.calls)


async def test_the_minute_check_keeps_a_waiting_entrys_orders_and_cancels_one_without_a_stop() -> (
    None
):
    stop = {"symbol": "SOLUSDT", "orderType": "STOP_MARKET", "quantity": "0.5"}
    target = {"symbol": "SOLUSDT", "orderType": "TAKE_PROFIT_MARKET"}
    kept = FakeGateway(algo=[stop, target], entries=[resting()])
    assert await FuturesTrader(kept).reconcile({}) == []
    assert kept.calls == [], "a waiting entry keeps its stop and targets"

    bare = FakeGateway(algo=[target], entries=[resting()])
    [cancel] = await FuturesTrader(bare).reconcile({})
    assert bare.calls == [("cancel entry", "SOLUSDT", "ati-wait-entry")]
    assert cancel.request == {"cancel": "order", "origClientOrderId": "ati-wait-entry"}


async def test_the_view_counts_a_waiting_entry_and_the_margin_it_holds() -> None:
    row = {**position("SOLUSDT", "0"), "openOrderInitialMargin": "41.6"}
    exchange = FakeGateway(positions=[row], entries=[resting(filled="0.2"), resting("ETHUSDT")])
    exchange._entries.append({**resting("XRPUSDT"), "reduceOnly": True})  # Closes only.
    view = await FuturesTrader(exchange).view()
    assert sorted(view.pending) == ["ETHUSDT", "SOLUSDT"] and view.positions == {}
    sol = view.pending["SOLUSDT"]
    assert sol.side is Side.LONG and sol.quantity == D("0.3") and sol.notional == D("24.96")
    assert view.order_margin == D("41.6")
    budget = Budget.of(view, capital=D(100), baseline=D(5000), day_start=D(5000))
    assert budget.available == D("58.4"), "margin held for a waiting entry is not free"
