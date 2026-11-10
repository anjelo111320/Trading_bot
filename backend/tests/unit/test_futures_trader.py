"""Opening, protecting and flattening Binance demo trades, against a fake exchange."""

import re
from decimal import Decimal
from typing import Any

import httpx

from tests.exchange_fakes import FakeGateway
from trading_intel.domain.signals import Side
from trading_intel.execution.binance_futures import BinanceError
from trading_intel.execution.orders import TradePlan, client_id, target_sizes
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
