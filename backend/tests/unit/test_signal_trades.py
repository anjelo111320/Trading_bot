"""What became of each signal's trade, for the Signals page (D065). Test data, not market data."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from typing import Any
from uuid import UUID, uuid7

from trading_intel.performance.results import Trade
from trading_intel.performance.signal_trades import (
    SignalTrade,
    exchange_trades,
    paper_trades,
    wanted,
)

AT = datetime(2026, 11, 13, 12, 15, tzinfo=UTC)
NOW = AT + timedelta(hours=2)


def market(key: UUID, symbol: str = "SOLUSDT", order_id: int = 911) -> dict[str, Any]:
    return {
        "recommendation_id": key, "symbol": symbol, "created_at": AT,
        "request": {"side": "SELL", "type": "MARKET", "quantity": "0.5"},
        "response": {"orderId": order_id, "executedQty": "0.5", "avgPrice": "84.10"},
    }  # fmt: skip


def limit(
    key: UUID, symbol: str = "BTCUSDT", till: datetime = NOW + timedelta(hours=1)
) -> dict[str, Any]:
    return {
        "recommendation_id": key, "symbol": symbol, "created_at": AT,
        "request": {"side": "BUY", "type": "LIMIT", "price": "90000", "quantity": "0.001",
                    "goodTillDate": int(till.timestamp() * 1000)},
        "response": {"orderId": 512, "executedQty": "0", "avgPrice": "0.00"},
    }  # fmt: skip


def short_sol(closed: bool, pnl: str = "0.30") -> Trade:
    """A short filled at 84.10 and, when closed, bought back at 83.50."""
    trade = Trade("SOLUSDT", "SHORT", AT + timedelta(seconds=2), 911, "trend_break_baseline")
    trade.sold, trade.sold_value, trade.size = D("0.5"), D("42.05"), D("0.5")
    if closed:
        trade.bought, trade.bought_value = D("0.5"), D("41.75")
        trade.closed_at, trade.pnl, trade.fees = AT + timedelta(hours=1), D(pnl), D("0.04")
    return trade


def test_a_closed_binance_trade_gives_its_fills_times_prices_and_net() -> None:
    key = uuid7()
    [trade] = exchange_trades([market(key)], [short_sol(True)], {}, frozenset(), NOW).values()
    assert trade.state == "won" and trade.net == D("0.26"), "realized 0.30 less 0.04 of fees"
    assert trade.opened_at == AT + timedelta(seconds=2), "the fill's time, not the order's"
    assert trade.closed_at == AT + timedelta(hours=1)
    assert trade.entry_price == D("84.10") and trade.exit_price == D("83.50")


def test_a_losing_trade_is_lost_and_an_exactly_even_one_is_even() -> None:
    lost, even = uuid7(), uuid7()
    found = exchange_trades(
        [market(lost), market(even, "ETHUSDT", 912)],
        [short_sol(True, "-0.20"), _even_eth()],
        {},
        frozenset(),
        NOW,
    )
    assert found[lost].state == "lost" and found[lost].net == D("-0.24")
    assert found[even].state == "even"


def _even_eth() -> Trade:
    trade = Trade("ETHUSDT", "LONG", AT, 912, "daily_trend", closed_at=AT + timedelta(hours=3))
    trade.pnl, trade.fees = D("0.05"), D("0.05")
    return trade


def test_an_open_binance_trade_shows_binances_open_profit_now() -> None:
    key = uuid7()
    found = exchange_trades(
        [market(key)], [short_sol(False)], {"SOLUSDT": D("0.15")}, frozenset(), NOW
    )
    assert found[key] == SignalTrade(
        "open", AT + timedelta(seconds=2), None, D("84.10"), None, D("0.15")
    )


def test_a_market_fill_counts_as_entered_before_its_fills_are_copied() -> None:
    key = uuid7()
    found = exchange_trades([market(key)], [], {"SOLUSDT": D("0.15")}, frozenset(), NOW)
    assert found[key].state == "open" and found[key].opened_at == AT, "the order's time stands in"
    assert found[key].entry_price == D("84.10") and found[key].net == D("0.15")


def test_a_limit_waits_only_while_it_is_the_coins_newest_entry_and_still_good() -> None:
    old, new, expired = uuid7(), uuid7(), uuid7()
    rows = [limit(old), limit(new), limit(expired, "ETHUSDT", NOW - timedelta(minutes=1))]
    found = exchange_trades(rows, [], {}, frozenset({"BTCUSDT", "ETHUSDT"}), NOW)
    assert found[new].state == "waiting"
    assert found[old].state == "not filled", "an older entry on the coin has expired"
    assert found[expired].state == "not filled", "past its good-till time"
    assert exchange_trades([limit(new)], [], {}, frozenset(), NOW)[new].state == "not filled"


def test_an_unfilled_market_entry_never_waits_and_a_refusal_is_named() -> None:
    unfilled, refused = uuid7(), uuid7()
    rows = [
        {**market(unfilled, "BTCUSDT"), "response": {"orderId": 7, "executedQty": "0"}},
        {"recommendation_id": refused, "symbol": "XRPUSDT", "created_at": AT,
         "request": {"leverage": 5}, "response": None, "error": "Binance 400 -4028"},
    ]  # fmt: skip
    found = exchange_trades(rows, [], {}, frozenset({"BTCUSDT"}), NOW)
    assert found[unfilled].state == "not filled"
    assert found[refused] == SignalTrade("refused")


def test_a_cancel_is_not_a_second_entry() -> None:
    key = uuid7()
    cancel = {
        "recommendation_id": key, "symbol": "BTCUSDT", "created_at": AT,
        "request": {"cancel": "order", "origClientOrderId": "ati-x-entry"},
        "response": {"orderId": 512, "status": "CANCELED"},
    }  # fmt: skip
    found = exchange_trades([limit(key), cancel], [], {}, frozenset(), NOW)
    assert found[key].state == "not filled"


def test_paper_positions_give_each_signals_trade() -> None:
    waiting, open_, won, cancelled = uuid7(), uuid7(), uuid7(), uuid7()
    rows = [
        {"recommendation_id": waiting, "status": "pending_entry", "opened_at": None,
         "closed_at": None, "average_entry": None, "realized_pnl": D(0), "exit_price": None},
        {"recommendation_id": open_, "status": "open", "opened_at": AT, "closed_at": None,
         "average_entry": D("90000"), "realized_pnl": D("1.5"), "exit_price": D("91000")},
        {"recommendation_id": won, "status": "closed", "opened_at": AT, "closed_at": NOW,
         "average_entry": D("90000"), "realized_pnl": D("2.25"), "exit_price": D("91500")},
        {"recommendation_id": cancelled, "status": "cancelled", "opened_at": None,
         "closed_at": None, "average_entry": None, "realized_pnl": D(0), "exit_price": None},
    ]  # fmt: skip
    found = paper_trades(rows)
    assert found[waiting] == SignalTrade("waiting")
    assert found[open_] == SignalTrade("open", AT, None, D("90000")), "no result while open"
    assert found[won] == SignalTrade("won", AT, NOW, D("90000"), D("91500"), D("2.25"))
    assert found[cancelled] == SignalTrade("not filled")


def test_the_result_filter() -> None:
    won, lost, waiting = SignalTrade("won"), SignalTrade("lost"), SignalTrade("waiting")
    refused, unfilled, open_ = (
        SignalTrade("refused"),
        SignalTrade("not filled"),
        SignalTrade("open"),
    )
    assert [wanted(t, "entered") for t in (won, lost, open_, waiting, None)] == [
        True, True, True, False, False,
    ]  # fmt: skip
    assert [wanted(t, "not_entered") for t in (None, refused, unfilled, waiting, won)] == [
        True, True, True, False, False,
    ]  # fmt: skip
    assert wanted(won, "won") and not wanted(lost, "won") and wanted(waiting, "waiting")
    assert wanted(open_, "open") and not wanted(None, "open")
