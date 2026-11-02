"""Golden tests: one for every fill rule in docs/10-BACKTESTING.md."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from typing import Any

import pytest

from tests.quant_data import START, candle
from trading_intel.domain.candles import ClosedCandle, Timeframe
from trading_intel.domain.signals import EntryType, Side
from trading_intel.paper_trading.simulator import (
    OrderStatus,
    SimulatedOrder,
    TradeSimulator,
    summarise,
)


def order(**overrides: Any) -> SimulatedOrder:
    values: dict[str, Any] = {
        "side": Side.LONG,
        "entry_type": EntryType.MARKET,
        "entry": D("100.00"),
        "stop": D("98.00"),
        "targets": (D("104.00"), D("106.00"), D("108.00")),
        "allocation": (D("0.5"), D("0.3"), D("0.2")),
        "quantity": D(10),
        "tick": D("0.01"),
        "lot_step": D("0.01"),
        "taker_fee": D("0.001"),
        "maker_fee": D("0.0002"),
        "half_spread": D("0.01"),
        "entry_slippage": D("0.02"),
        "stop_slippage": D("0.05"),
        "placed_at": START,
        "expires_at": START + timedelta(hours=2),
    }
    return SimulatedOrder(**{**values, **overrides})


def bar(
    index: int, open_: str, high: str, low: str, close: str, volume: str = "1000"
) -> ClosedCandle:
    return candle(
        index, float(open_), float(high), float(low), float(close), float(volume), Timeframe.M1
    )


def run(simulator: TradeSimulator, *bars: ClosedCandle) -> TradeSimulator:
    for item in bars:
        simulator.on_candle(item)
    return simulator


def test_market_entry_fills_at_the_next_open_plus_costs() -> None:
    sim = run(TradeSimulator(order()), bar(0, "100.50", "101", "100", "100.80"))
    entry = sim.fills[0]
    assert entry.kind == "entry"
    assert entry.price == D("100.53")
    assert entry.fee == D("0.001") * D("100.53") * 10
    assert entry.spread_cost == D("0.10")
    assert entry.slippage_cost == D("0.20")


def test_candles_before_the_order_existed_are_ignored() -> None:
    placed = order(placed_at=START + timedelta(minutes=5))
    sim = run(TradeSimulator(placed), bar(1, "100", "101", "99", "100"))
    assert sim.fills == []


def test_limit_fills_only_when_price_trades_through() -> None:
    limit = order(entry_type=EntryType.LIMIT, entry=D("99.00"))
    touched = run(TradeSimulator(limit), bar(0, "100", "100", "99.00", "99.50"))
    assert touched.status is OrderStatus.PENDING
    through = run(TradeSimulator(limit), bar(0, "100", "100", "98.99", "99.50"))
    assert through.status is OrderStatus.OPEN
    assert through.fills[0].price == D("99.00")
    assert through.fills[0].spread_cost == 0
    assert through.fills[0].fee == D("0.0002") * D("99.00") * 10


def test_short_limit_mirrors_the_rule() -> None:
    limit = order(
        side=Side.SHORT,
        entry_type=EntryType.LIMIT,
        entry=D("101.00"),
        stop=D("103.00"),
        targets=(D("97.00"),),
        allocation=(D(1),),
    )
    assert run(TradeSimulator(limit), bar(0, "100", "101.00", "100", "100")).status is (
        OrderStatus.PENDING
    )
    assert run(TradeSimulator(limit), bar(0, "100", "101.01", "100", "100")).status is (
        OrderStatus.OPEN
    )


def test_stop_entry_needs_a_trade_through_and_pays_costs() -> None:
    stop_entry = order(entry_type=EntryType.STOP, entry=D("101.00"), stop=D("99.00"))
    assert run(TradeSimulator(stop_entry), bar(0, "100", "101.00", "100", "101")).status is (
        OrderStatus.PENDING
    )
    sim = run(TradeSimulator(stop_entry), bar(0, "100", "101.50", "100", "101"))
    assert sim.fills[0].price == D("101.03")


def test_stop_entry_gapping_past_the_level_fills_at_the_worse_open() -> None:
    stop_entry = order(entry_type=EntryType.STOP, entry=D("101.00"), stop=D("99.00"))
    sim = run(TradeSimulator(stop_entry), bar(0, "102.00", "103", "101.5", "102.5"))
    assert sim.fills[0].price == D("102.03")


def test_stop_loss_fills_at_the_stop_plus_slippage() -> None:
    sim = run(
        TradeSimulator(order()),
        bar(0, "100", "100.5", "99.5", "100"),
        bar(1, "100", "100", "97.5", "98"),
    )
    stop = sim.fills[-1]
    assert stop.kind == "stop"
    assert stop.price == D("97.94")
    assert sim.status is OrderStatus.CLOSED


def test_a_gap_through_the_stop_fills_at_the_worse_open() -> None:
    sim = run(
        TradeSimulator(order()),
        bar(0, "100", "100.5", "99.5", "100"),
        bar(1, "95", "96", "94", "95"),
    )
    assert sim.fills[-1].price == D("94.94")


def test_target_fills_only_on_a_trade_through() -> None:
    touched = run(
        TradeSimulator(order()),
        bar(0, "100", "100.5", "99.5", "100"),
        bar(1, "100", "104.00", "100", "103"),
    )
    assert [f.kind for f in touched.fills] == ["entry"]
    through = run(
        TradeSimulator(order()),
        bar(0, "100", "100.5", "99.5", "100"),
        bar(1, "100", "104.01", "100", "103"),
    )
    assert through.fills[-1].kind == "tp1"
    assert through.fills[-1].price == D("104.00")
    assert through.fills[-1].quantity == D(5)


def test_a_gap_through_a_target_gets_no_credit_for_the_better_price() -> None:
    sim = run(
        TradeSimulator(order()),
        bar(0, "100", "100.5", "99.5", "100"),
        bar(1, "105", "105.5", "104.5", "105"),
    )
    assert sim.fills[1].price == D("104.00")


def test_stop_comes_first_when_a_candle_reaches_both() -> None:
    sim = run(
        TradeSimulator(order()),
        bar(0, "100", "100.5", "99.5", "100"),
        bar(1, "100", "110", "90", "100"),
    )
    assert [f.kind for f in sim.fills] == ["entry", "stop"]


def test_entry_and_stop_in_one_candle_counts_as_entered_then_stopped() -> None:
    sim = run(TradeSimulator(order()), bar(0, "100", "100.5", "97", "98"))
    assert [f.kind for f in sim.fills] == ["entry", "stop"]


def test_several_targets_can_fill_in_one_candle() -> None:
    sim = run(
        TradeSimulator(order()),
        bar(0, "100", "100.5", "99.5", "100"),
        bar(1, "100", "109", "100", "108"),
    )
    assert [f.kind for f in sim.fills] == ["entry", "tp1", "tp2", "tp3"]
    assert [f.quantity for f in sim.fills[1:]] == [D(5), D(3), D(2)]
    assert sim.status is OrderStatus.CLOSED


def test_the_last_target_takes_the_rounding_remainder() -> None:
    sim = run(
        TradeSimulator(order(quantity=D("0.07"), allocation=(D("0.5"), D("0.3"), D("0.2")))),
        bar(0, "100", "100.5", "99.5", "100"),
        bar(1, "100", "109", "100", "108"),
    )
    assert sum(f.quantity for f in sim.fills[1:]) == D("0.07")


def test_size_is_capped_by_candle_liquidity() -> None:
    sim = run(TradeSimulator(order()), bar(0, "100", "100.5", "99.5", "100", volume="100"))
    assert sim.fills[0].quantity == D(5)


def test_a_candle_with_no_volume_fills_nothing() -> None:
    sim = run(TradeSimulator(order()), bar(0, "100", "100", "100", "100", volume="0"))
    assert sim.status is OrderStatus.PENDING


def test_an_unfilled_order_cancels_at_expiry() -> None:
    limit = order(
        entry_type=EntryType.LIMIT, entry=D("99.00"), expires_at=START + timedelta(minutes=1)
    )
    sim = run(TradeSimulator(limit), bar(1, "100", "100", "99.5", "100"))
    assert sim.status is OrderStatus.CANCELLED
    assert sim.fills[0].kind == "expiry"


def test_an_open_position_ignores_expiry() -> None:
    market = order(expires_at=START + timedelta(minutes=1))
    sim = run(
        TradeSimulator(market),
        bar(0, "100", "100.5", "99.5", "100"),
        bar(5, "100", "100.5", "99.5", "100"),
    )
    assert sim.status is OrderStatus.OPEN


def test_a_pending_order_is_invalidated_by_a_close_beyond_the_stop() -> None:
    stop_entry = order(entry_type=EntryType.STOP, entry=D("101.00"), stop=D("99.00"))
    sim = run(TradeSimulator(stop_entry), bar(0, "100", "100.5", "98", "98.5"))
    assert sim.status is OrderStatus.CANCELLED
    assert sim.fills[0].kind == "invalidation"


def test_a_pending_order_survives_a_candle_that_stays_above_the_stop() -> None:
    stop_entry = order(entry_type=EntryType.STOP, entry=D("101.00"), stop=D("99.00"))
    sim = run(TradeSimulator(stop_entry), bar(0, "100", "100.5", "98", "99.5"))
    assert sim.status is OrderStatus.PENDING


def test_a_long_pays_positive_funding_and_a_short_receives_it() -> None:
    long = run(TradeSimulator(order()), bar(0, "100", "100.5", "99.5", "100"))
    short_order = order(
        side=Side.SHORT, stop=D("102.00"), targets=(D("96.00"),), allocation=(D(1),)
    )
    short = run(TradeSimulator(short_order), bar(0, "100", "100.5", "99.5", "100"))
    at = START + timedelta(minutes=30)
    assert long.on_funding(at, D("0.0001"), D(100))[0].funding == D("-0.1000")
    assert short.on_funding(at, D("0.0001"), D(100))[0].funding == D("0.1000")


def test_funding_is_not_charged_before_entry() -> None:
    assert TradeSimulator(order()).on_funding(START, D("0.0001"), D(100)) == []


def test_results_add_up_by_hand() -> None:
    sim = run(
        TradeSimulator(order(quantity=D(10), targets=(D("104.00"),), allocation=(D(1),))),
        bar(0, "100", "100.5", "99.5", "100"),
        bar(1, "100", "105", "100", "104"),
    )
    result = summarise(Side.LONG, sim.fills)
    entry_fee = D("0.001") * D("100.03") * 10
    exit_fee = D("0.0002") * D("104.00") * 10
    assert result.gross_pnl == D("39.70")
    assert result.fees == entry_fee + exit_fee
    assert result.net_pnl == D("39.70") - entry_fee - exit_fee
    assert result.exit_reason == "tp1"


def test_an_unfilled_trade_has_no_result() -> None:
    limit = order(
        entry_type=EntryType.LIMIT, entry=D("99.00"), expires_at=START + timedelta(minutes=1)
    )
    sim = run(TradeSimulator(limit), bar(1, "100", "100", "99.5", "100"))
    result = summarise(Side.LONG, sim.fills)
    assert not result.entered
    assert result.net_pnl == 0
    assert result.exit_reason == "expiry"


def test_a_finished_trade_ignores_later_candles() -> None:
    sim = run(TradeSimulator(order()), bar(0, "100", "100.5", "97", "98"))
    count = len(sim.fills)
    sim.on_candle(bar(1, "100", "120", "90", "100"))
    assert len(sim.fills) == count


@pytest.mark.parametrize("seed", range(5))
def test_the_same_candles_always_give_identical_fills(seed: int) -> None:
    bars = [bar(i, "100", str(101 + seed), str(99 - i * 0.2), "100") for i in range(10)]
    first = run(TradeSimulator(order()), *bars)
    second = run(TradeSimulator(replace(order())), *bars)
    assert first.fills == second.fills
