"""What each Binance demo order means in USDT (D057). Test data, not market data."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from typing import Any

from trading_intel.performance.orders import figure_orders
from trading_intel.performance.results import EntryOrder, Trade

AT = datetime(2026, 11, 11, 15, tzinfo=UTC)
PLAN = EntryOrder(order_id=911, strategy="trend_break_baseline", planned_risk=D("1"))


def short_pepe() -> list[dict[str, Any]]:
    """A short entry, its whole-position stop and two targets, newest first as the API lists."""
    return [
        {"symbol": "PEPE", "kind": "tp2", "recommendation_id": "r1",
         "request": {"side": "BUY", "triggerPrice": "0.0046", "quantity": "1500"}, "response": {}},
        {"symbol": "PEPE", "kind": "tp1", "recommendation_id": "r1",
         "request": {"side": "BUY", "triggerPrice": "0.0047", "quantity": "2500"},
         "response": {"algoId": 2}},
        {"symbol": "PEPE", "kind": "stop", "recommendation_id": "r1",
         "request": {"side": "BUY", "triggerPrice": "0.0051", "closePosition": True},
         "response": {"algoId": 1}},
        {"symbol": "PEPE", "kind": "entry", "recommendation_id": "r1",
         "request": {"side": "SELL", "type": "MARKET", "quantity": "4000"},
         "response": {"orderId": 911, "executedQty": "4000", "avgPrice": "0.0049"}},
    ]  # fmt: skip


def test_a_targets_profit_and_the_stops_loss_if_they_fill_before_fees() -> None:
    rows = short_pepe()
    rows[0]["response"] = {"algoId": 3}
    tp2, tp1, stop, entry = figure_orders(rows, [], [], [PLAN], {"PEPE": D("0.4")}, frozenset())
    assert tp1.if_hit == D("0.5000") and tp2.if_hit == D("0.4500"), "a short gains as price falls"
    assert stop.if_hit == D("-0.8000"), "the whole position at the stop"
    assert stop.value == D("20.4000") and tp1.value == D("11.7500")
    assert entry.value == D("19.6000") and entry.risk == D(1)
    assert entry.state == "open" and entry.now == D("0.4"), "Binance's unrealized profit"
    assert entry.fill_price == D("0.0049")
    assert {f.strategy for f in (tp2, tp1, stop, entry)} == {"trend_break_baseline"}


def test_a_closed_trade_shows_its_net_and_its_real_entry() -> None:
    trade = Trade("PEPE", "SHORT", AT, 911, "trend_break_baseline", D(1), closed_at=AT)
    trade.sold, trade.sold_value, trade.size = D(4000), D("19.8"), D(4000)  # Filled at 0.00495.
    trade.pnl, trade.fees = D("1.13"), D("0.02")
    *_, stop, entry = figure_orders(short_pepe(), [trade], [], [PLAN], {}, frozenset())
    assert entry.state == "won" and entry.now == D("1.11")
    assert stop.if_hit == D("-0.6000"), "measured from the fill Binance made, 0.00495"
    assert entry.fill_price == D("0.00495")


def test_cancels_refusals_and_orders_of_no_known_trade_have_no_figures() -> None:
    rows = [
        {"symbol": "SOL", "kind": "stop", "recommendation_id": None,
         "request": {"side": "BUY", "triggerPrice": "92"}, "response": {"algoId": 9}},
        {"symbol": "PEPE", "kind": "stop", "recommendation_id": "r1",
         "request": {"cancel": "algoOrder", "algoId": 1}, "response": {"code": "200"}},
        *short_pepe(),
    ]  # fmt: skip
    rows[2]["response"] = None  # The second target was refused.
    figures = figure_orders(rows, [], [], [PLAN], {}, frozenset())
    assert figures[0].if_hit is None and figures[0].strategy is None
    assert figures[1].if_hit is None and figures[1].strategy == "trend_break_baseline"
    assert figures[2].if_hit is None


def test_a_limit_entry_waiting_or_expired() -> None:
    rows = [
        {"symbol": "ETH", "kind": "entry", "recommendation_id": "r2",
         "request": {"side": "BUY", "type": "LIMIT", "price": "2058.4", "quantity": "0.02"},
         "response": {"orderId": 77, "status": "NEW", "executedQty": "0"}},
    ]  # fmt: skip
    gap = EntryOrder(77, "fvg_choch", D("1"))
    [waiting] = figure_orders(rows, [], [], [gap], {}, frozenset({"ETH"}))
    assert waiting.state == "waiting" and waiting.value == D("41.168") and waiting.now is None
    assert waiting.fill_price is None, "not filled yet"
    [expired] = figure_orders(rows, [], [], [gap], {}, frozenset())
    assert expired.state == "not filled"


def test_only_the_coins_newest_limit_entry_before_its_good_till_time_is_waiting() -> None:
    """Regression (D065's open gap): an expired limit entry showed as waiting whenever a newer
    one on its coin was resting. Now the rule is the Signals page's."""
    now = datetime(2026, 11, 15, 12, tzinfo=UTC)
    before, later = (
        int((now - timedelta(hours=1)).timestamp() * 1000),
        int((now + timedelta(hours=1)).timestamp() * 1000),
    )
    old = {"symbol": "ETH", "kind": "entry", "recommendation_id": "r1",
           "created_at": now - timedelta(hours=3),
           "request": {"side": "BUY", "type": "LIMIT", "price": "2000", "quantity": "0.02",
                       "goodTillDate": before},
           "response": {"orderId": 76, "status": "NEW", "executedQty": "0"}}  # fmt: skip
    new = {**old, "recommendation_id": "r2", "created_at": now - timedelta(minutes=5),
           "request": {**old["request"], "price": "2058.4", "goodTillDate": later},
           "response": {**old["response"], "orderId": 77}}  # fmt: skip
    plans = [EntryOrder(76, "fvg_choch", D("1")), EntryOrder(77, "fvg_choch", D("1"))]
    newest_first = [new, old]
    waiting, expired = figure_orders(newest_first, [], [], plans, {}, frozenset({"ETH"}), now)
    assert waiting.state == "waiting"
    assert expired.state == "not filled", "the older entry is not the one in the book"
    late = {**new, "request": {**new["request"], "goodTillDate": before}}
    [past] = figure_orders([late], [], [], plans, {}, frozenset({"ETH"}), now)
    assert past.state == "not filled", "past its good-till time"
