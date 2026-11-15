"""The coin scorecard (D068): entry quality, live results, and the published backtests."""

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

from tests.quant_data import candle
from trading_intel.core.settings import REPOSITORY_ROOT
from trading_intel.domain.candles import ClosedCandle, Timeframe
from trading_intel.domain.signals import Side
from trading_intel.performance.scorecard import (
    EVIDENCE,
    NEVER_TESTED,
    NOT_ON_COIN,
    EnteredTrade,
    Scored,
    cards,
    dedupe,
    entry_quality,
    first_hour_r,
    live_result,
    slippage_r,
)
from trading_intel.trade_signals.portfolio import LEFT_OUT

OPENED = datetime(2026, 11, 14, 13, 0, 15, tzinfo=UTC)


def trade(**changes: object) -> EnteredTrade:
    values: dict[str, object] = {
        "symbol": "BTCUSDT",
        "strategy": "daily_trend",
        "side": Side.LONG,
        "planned_entry": D(100),
        "planned_stop": D(98),
        "filled": D(100),
        "opened_at": OPENED,
    }
    return EnteredTrade(**{**values, **changes})  # type: ignore[arg-type]


def minute(start: datetime, high: str, low: str) -> ClosedCandle:
    middle = (float(high) + float(low)) / 2
    bar = candle(0, middle, float(high), float(low), middle, timeframe=Timeframe.M1)
    close = Timeframe.M1.close_time(start)
    return bar.model_copy(update={"open_time": start, "close_time": close})


def test_slippage_is_how_much_worse_than_planned_the_entry_filled_in_r() -> None:
    assert slippage_r(trade(filled=D("100.2"))) == D("0.1")
    short = trade(side=Side.SHORT, planned_stop=D(102))
    assert slippage_r(trade(side=Side.SHORT, planned_stop=D(102), filled=D("99.8"))) == D("0.1")
    assert slippage_r(short) == 0
    assert slippage_r(trade(planned_stop=D(100))) is None, "no risk, no R"


def test_the_first_hour_is_the_furthest_the_price_went_against_the_fill() -> None:
    start = OPENED.replace(second=0)
    candles = [
        minute(start, "101", "90"),  # The fill's own minute traded partly before the fill.
        minute(start + timedelta(minutes=1), "100.5", "99"),
        minute(start + timedelta(minutes=30), "101", "98.5"),
        minute(start + timedelta(minutes=61), "100", "80"),  # After the hour.
    ]
    assert first_hour_r(trade(), candles) == D("0.75")
    short = trade(side=Side.SHORT, planned_stop=D(102))
    assert first_hour_r(short, candles) == D("0.5")
    assert first_hour_r(trade(), []) is None
    rising = [minute(start + timedelta(minutes=5), "103", "100.5")]
    assert first_hour_r(trade(), rising) == 0, "never against: zero"


def test_entries_and_results_are_summed_once_per_setup() -> None:
    won, lost, still_open = trade(r=D("2.4")), trade(r=D(-1)), trade()
    scored = [
        Scored(won, D("0.1"), D("0.2")),
        Scored(lost, D("0.3"), D("0.9")),
        Scored(still_open, D("-0.1"), None),
    ]
    live = live_result(scored)
    assert (live.entered, live.closed, live.won, live.mean_r) == (3, 2, 1, D("0.7"))
    quality = entry_quality(scored)
    assert (quality.trades, quality.slippage_r, quality.first_hour_r) == (2, D("0.2"), D("0.55"))
    assert quality.went_against == 1
    twice = [trade(), trade(opened_at=OPENED + timedelta(seconds=20)), trade(symbol="ETHUSDT")]
    assert len(dedupe(twice)) == 2, "the same setup on two accounts is one trade"


def test_every_strategy_says_what_backs_it_on_every_coin() -> None:
    scored = [Scored(trade(strategy="trend_break_baseline", r=D(-1)), None, None)]
    left_out = {("fvg_choch", "BTCUSDT")}
    strategies = ("daily_trend", "fvg_choch", "trend_break_baseline", "news_move")
    btc, other = cards(["BTCUSDT", "ADAUSDT"], strategies, scored, left_out)
    trend, fvg, rule, news = btc.strategies
    assert trend.evidence == EVIDENCE[("daily_trend", "BTCUSDT")] and trend.untested is None
    assert fvg.left_out and not trend.left_out
    assert rule.evidence == EVIDENCE[("trend_break_baseline", "BTCUSDT")]
    assert news.evidence is None and news.untested == NEVER_TESTED["news_move"]
    assert rule.live.closed == 1 and btc.live.entered == 1
    assert other.strategies[0].untested == NOT_ON_COIN and other.live.entered == 0


ROW = re.compile(
    r"^\| (?P<coin>[A-Z0-9]+USDT) \| (?P<trades>\d+) \| [^|]+ \| (?P<mean>[+-]?\d\.\d{3}) \| "
    r"(?P<low>[+-]?\d\.\d{2}) to (?P<high>[+-]?\d\.\d{2}) \|"
)


def published(report: str, heading: str) -> dict[str, tuple[int, D, D, D]]:
    """The per-coin rows under one heading of a study report."""
    lines = (REPOSITORY_ROOT / "docs" / "reports" / report).read_text().splitlines()
    start = lines.index(heading)
    rows: dict[str, tuple[int, D, D, D]] = {}
    for line in lines[start + 1 :]:
        if line.startswith("## ") or line.startswith("### "):
            break
        match = ROW.match(line)
        if match:
            rows[match["coin"]] = (
                int(match["trades"]), D(match["mean"]), D(match["low"]), D(match["high"])
            )  # fmt: skip
    return rows


def test_the_backtests_match_the_published_reports_row_for_row() -> None:
    reports: dict[str, dict[str, tuple[int, D, D, D]]] = {
        "pattern_breakout": published("coin-replication.md", "## pattern_breakout"),
        "daily_trend": published("coin-replication.md", "## daily_trend"),
        "fvg_choch": published("fvg-choch.md", "## By Coin, Normal Costs"),
        "trend_break_baseline": published("new-coin-study.md", "### trend_break_baseline"),
        "trend_break_loose": published("new-coin-study.md", "### trend_break_loose"),
    }
    for strategy in ("daily_trend", "pattern_breakout", "fvg_choch"):
        reports[strategy] |= published("new-coin-study.md", f"### {strategy}")
    for (strategy, coin), evidence in EVIDENCE.items():
        expected = reports[strategy][coin]
        assert (evidence.trades, evidence.mean_r, evidence.low, evidence.high) == expected, (
            strategy,
            coin,
        )
    assert sum(len(rows) for rows in reports.values()) == len(EVIDENCE) == 50


def test_the_coins_left_out_are_the_ones_the_studies_found_losing() -> None:
    """docs/33 left none out; docs/42 left out four, by its pre-registered rule."""
    report = (REPOSITORY_ROOT / "docs" / "reports" / "new-coin-study.md").read_text()
    [line] = [row for row in report.splitlines() if row.startswith("- Left out, lost with")]
    named = line.split(": ", 1)[1].rstrip(".").split(", ")
    assert {tuple(pair.split(" on ")) for pair in named} == LEFT_OUT
