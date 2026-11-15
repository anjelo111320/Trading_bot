"""Completed trades rebuilt from Binance fills, and their statistics (D057). Test data only."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from itertools import count
from typing import Literal

from trading_intel.performance.results import (
    EntryOrder,
    Fill,
    Funding,
    breakdown,
    equity_curve,
    median_hold_hours,
    rebuild,
    streaks,
    summarise,
)

T0 = datetime(2026, 11, 11, tzinfo=UTC)
ids = count(1)


def fill(
    side: Literal["BUY", "SELL"],
    qty: str,
    price: str,
    pnl: str = "0",
    fee: str = "0.01",
    order: int = 0,
    hours: float = 0,
    symbol: str = "PEPEUSDT",
    asset: str = "USDT",
) -> Fill:
    return Fill(
        symbol, next(ids), order or next(ids) + 10_000, side, D(price), D(qty), D(pnl), D(fee),
        asset, T0 + timedelta(hours=hours),
    )  # fmt: skip


BOT = EntryOrder(order_id=501, strategy="trend_break_baseline", planned_risk=D("0.5"))


def test_a_long_closed_in_two_parts_is_one_trade_with_its_strategy_and_r() -> None:
    fills = [
        fill("BUY", "100", "1.00", order=501, fee="0.05"),
        fill("SELL", "50", "1.02", pnl="1.00", fee="0.025", hours=1),  # A target.
        fill("SELL", "50", "0.99", pnl="-0.50", fee="0.025", hours=2),  # The stop.
    ]
    [trade], still = rebuild(fills, [], [BOT])
    assert still == []
    assert trade.side == "LONG" and trade.strategy == "trend_break_baseline"
    assert trade.pnl == D("0.50") and trade.fees == D("0.100") and trade.net == D("0.400")
    assert trade.r == D("0.8") and trade.won
    assert trade.entry_price == D("1.00") and trade.exit_price == D("1.005")
    assert trade.size == D(100) and trade.closed_at == T0 + timedelta(hours=2)


def test_a_short_and_a_trade_the_bot_did_not_open() -> None:
    fills = [
        fill("SELL", "2", "50", symbol="SOLUSDT", order=777),
        fill("BUY", "2", "52", pnl="-4", symbol="SOLUSDT", hours=3),
    ]
    [trade], _ = rebuild(fills, [], [BOT])
    assert trade.side == "SHORT" and trade.strategy is None and trade.r is None
    assert trade.entry_price == D(50) and trade.exit_price == D(52) and not trade.won


def test_a_fill_through_flat_closes_one_trade_and_opens_the_next() -> None:
    fills = [
        fill("BUY", "1", "100", order=501, fee="0.10"),
        fill("SELL", "3", "110", pnl="10", fee="0.30", hours=1),
    ]
    [first], [second] = rebuild(fills, [], [BOT])
    assert first.pnl == D(10) and first.fees == D("0.20"), (
        "the fill's profit and a third of its fee"
    )
    assert second.side == "SHORT" and second.pnl == 0 and second.fees == D("0.20")
    assert second.size == D(2) and second.strategy is None


def test_funding_goes_to_the_trade_open_on_its_coin_then() -> None:
    fills = [fill("BUY", "1", "100", order=501), fill("SELL", "1", "101", pnl="1", hours=10)]
    funding = [
        Funding("PEPEUSDT", D("-0.02"), T0 + timedelta(hours=8)),
        Funding("PEPEUSDT", D("-0.50"), T0 + timedelta(hours=16)),  # After it closed.
        Funding("SOLUSDT", D("-0.50"), T0 + timedelta(hours=8)),  # Another coin.
    ]
    [trade], _ = rebuild(fills, funding, [BOT])
    assert trade.funding == D("-0.02") and trade.net == D("1") - D("0.02") - D("0.02")


def test_fees_in_another_asset_are_kept_apart() -> None:
    [trade], _ = rebuild(
        [fill("BUY", "1", "100", asset="BNB"), fill("SELL", "1", "100", hours=1)], [], []
    )
    assert trade.fees == D("0.01") and trade.other_fees == {"BNB": D("0.01")}


def test_an_open_position_is_not_a_completed_trade() -> None:
    closed, still = rebuild([fill("BUY", "1", "100", order=501)], [], [BOT])
    assert closed == [] and len(still) == 1 and still[0].closed_at is None


def trades(*nets: str) -> list:
    """Closed bot trades with these net results, one hour apart, each risking 1 USDT."""
    made = []
    for hour, net in enumerate(nets):
        entry = EntryOrder(order_id=900 + hour, strategy="daily_trend", planned_risk=D(1))
        pair = [
            fill("BUY", "1", "100", order=entry.order_id, fee="0", hours=hour),
            fill("SELL", "1", "100", pnl=net, fee="0", hours=hour + 0.5),
        ]
        made += rebuild(pair, [], [entry])[0]
    return made


def test_the_summary_counts_wins_and_divides_what_was_won_by_what_was_lost() -> None:
    summary = summarise(trades("2", "-1", "3", "-1"))
    assert (summary.trades, summary.wins, summary.losses) == (4, 2, 2)
    assert summary.win_rate == D("0.5") and summary.net == D(3)
    assert summary.profit_factor == D("2.5") and summary.average_r == D("0.75")
    assert summary.average_win == D("2.5") and summary.average_loss == D(-1)
    assert summary.best == D(3) and summary.worst == D(-1)


def test_nothing_lost_has_no_profit_factor_and_no_trades_no_rates() -> None:
    assert summarise(trades("1")).profit_factor is None
    empty = summarise([])
    assert empty.trades == 0 and empty.win_rate is None and empty.average_r is None


def test_groups_are_listed_most_profitable_first() -> None:
    made = trades("1", "-2", "5")
    rows = breakdown(made, lambda t: "even" if made.index(t) % 2 == 0 else "odd")
    assert [(name, s.net) for name, s in rows] == [("even", D(6)), ("odd", D(-2))]


def test_the_equity_curve_and_its_deepest_fall() -> None:
    curve = equity_curve(trades("10", "-5", "-10", "20"), D(100), T0)
    assert [p[1] for p in curve.points] == [D(100), D(110), D(105), D(95), D(115)]
    assert curve.drawdown == D(15) and curve.drawdown_fraction == D(15) / D(110)


def test_streaks_and_hold_time() -> None:
    made = trades("1", "1", "-1", "-1", "-1", "2")
    assert streaks(made).longest_wins == 2 and streaks(made).longest_losses == 3
    assert streaks(made).current == 1
    assert median_hold_hours(made) == D("0.5")
