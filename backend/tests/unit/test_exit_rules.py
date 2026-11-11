"""The exit rules study's parts (docs/37): the market exit, the rules, the replay and the checks."""

from datetime import datetime, timedelta
from decimal import Decimal as D
from typing import Any

import pytest

from tests.quant_data import START
from tests.unit.test_backtesting import FAR_END, EverySetupCandle, candles, engine
from tests.unit.test_simulator import bar, order
from trading_intel.backtesting.exits import (
    EXIT,
    Action,
    Breakeven,
    CheckCounts,
    OpenTrade,
    StallExit,
    SwingTrail,
    TradeChecks,
    breakeven_stop,
    prior_median_ranges,
    replay,
)
from trading_intel.backtesting.metrics import bootstrap_interval
from trading_intel.domain.candles import Timeframe
from trading_intel.domain.signals import Side
from trading_intel.market_structure.swings import Swing
from trading_intel.paper_trading.simulator import OrderStatus, TradeSimulator, summarise


class TrailingEverySetupCandle(EverySetupCandle):
    """The stub strategy with a trail that tightens the stop by 0.5 at every setup close."""

    def trailing_stop(self, moment: datetime, side: Side, stop: D) -> D | None:
        return stop + D("0.5")


@pytest.mark.parametrize("strategy", [EverySetupCandle, TrailingEverySetupCandle])
def test_a_replay_with_no_rule_reproduces_the_engine(strategy: type[EverySetupCandle]) -> None:
    """The study is void if this fails: every comparison rests on it."""
    minutes = candles(Timeframe.M1, 6000)
    setup = candles(Timeframe.M15, 400, 15)
    stub = strategy(setup)
    result = engine(minutes, setup, strategy=stub, skip_signals_in_trade=True).run(START, FAR_END)
    assert len(result.trades) > 3
    closes = {c.close_time: c.close for c in setup}
    opens = [c.open_time for c in minutes]
    trail = getattr(stub, "trailing_stop", None)
    for trade in result.trades:
        again = replay(
            trade.order, trade.signal_time, minutes, opens, closes, (), FAR_END, trail=trail
        )
        assert again.result == trade.result and not again.acted


def test_a_market_exit_fills_at_the_next_open_with_a_stops_costs() -> None:
    sim = TradeSimulator(order())
    assert not sim.request_exit(), "nothing to close before the entry"
    sim.on_candle(bar(0, "100.50", "101", "100", "100.80"))
    assert sim.request_exit()
    # This candle also reaches the stop and a target. Neither applies: the position is gone.
    sim.on_candle(bar(1, "101.00", "105", "97", "101"))
    exit_fill = sim.fills[-1]
    assert sim.status is OrderStatus.CLOSED and exit_fill.kind == "exit"
    assert exit_fill.price == D("100.94")  # The open, less half the spread and the slippage.
    assert exit_fill.fee == D("0.001") * D("100.94") * 10
    outcome = summarise(Side.LONG, sim.fills)
    assert outcome.exit_reason == "exit" and outcome.exit_price == D("100.94")
    assert outcome.gross_pnl == (D("100.94") - D("100.53")) * 10


def test_the_breakeven_stop_nets_about_zero_after_costs() -> None:
    plan = order()
    level = breakeven_stop(plan, D("100.53"))
    assert level == D("100.80")  # 100.53 + 0.01 + 0.05 + 2 x 0.1% of 100.53, rounded up.
    sim = TradeSimulator(plan)
    sim.on_candle(bar(0, "100.50", "101", "100", "100.80"))
    assert sim.move_stop(level)
    sim.on_candle(bar(1, "100.90", "101", "100.70", "100.75"))
    assert D(0) <= summarise(Side.LONG, sim.fills).net_pnl < D("0.2")
    assert breakeven_stop(order(side=Side.SHORT, stop=D(102)), D("99.47")) == D("99.21")


def trade(**changes: Any) -> OpenTrade:
    values: dict[str, Any] = {
        "side": Side.LONG,
        "entry": D(100),
        "risk": D(2),
        "stop": D(98),
        "breakeven": D("100.30"),
        "best": D("102.50"),
        "stale": 6,
        "close": D(101),
        "targets_hit": 0,
        "moment": START,
    }
    return OpenTrade(**{**values, **changes})


def test_breakeven_waits_for_plus_one_r() -> None:
    assert Breakeven().decide(trade(best=D("101.90"))) is None
    assert Breakeven().decide(trade(best=D(102))) == D("100.30")
    assert Breakeven().decide(trade(best=None)) is None


def test_the_stall_exit_needs_profit_no_progress_and_no_target_yet() -> None:
    rule = StallExit()
    assert rule.decide(trade()) == EXIT
    assert rule.decide(trade(stale=5)) is None, "still making progress"
    assert rule.decide(trade(close=D("100.90"))) is None, "less than +0.5R"
    assert rule.decide(trade(targets_hit=1)) is None, "a target already paid"
    short = trade(side=Side.SHORT, stop=D(102), best=D(97), close=D(99))
    assert rule.decide(short) == EXIT


def swing(kind: str, price: str, confirmed_hours: int) -> Swing:
    at = START + timedelta(hours=confirmed_hours)
    return Swing(kind, 0, float(price), at, 0, at)  # type: ignore[arg-type]


def test_the_swing_trail_uses_only_swings_confirmed_by_then() -> None:
    rule = SwingTrail(
        [swing("low", "99.5", 1), swing("high", "104", 2), swing("low", "101.25", 5)], D("0.01")
    )
    moment = START + timedelta(hours=3)
    assert rule.decide(trade(moment=moment)) == D("99.50"), "the later low is not known yet"
    assert rule.decide(trade(moment=START + timedelta(hours=5))) == D("101.25")
    assert rule.decide(trade(best=D(101), moment=moment)) is None, "before +1R"
    short = trade(side=Side.SHORT, stop=D(102), best=D(97), moment=moment)
    assert rule.decide(short) == D("104.00")
    assert SwingTrail([], D("0.01")).decide(trade()) is None


class ExitAtOnce:
    name = "exit_at_once"

    def decide(self, trade: OpenTrade) -> Action:
        return EXIT


def test_a_rule_acts_from_the_next_fill_candle() -> None:
    minutes = candles(Timeframe.M1, 6000)
    setup = candles(Timeframe.M15, 400, 15)
    backtest = engine(minutes, setup, strategy=EverySetupCandle(setup), skip_signals_in_trade=True)
    first = backtest.run(START, FAR_END).trades[0]
    closes = {c.close_time: c.close for c in setup}
    opens = [c.open_time for c in minutes]
    again = replay(
        first.order, first.signal_time, minutes, opens, closes, (), FAR_END, rule=ExitAtOnce()
    )
    assert again.acted and again.result.exit_reason == "exit"
    assert again.result.entry_time is not None and again.result.exit_time is not None
    decided = min(t for t in closes if t > again.result.entry_time)
    exit_candle = next(c for c in minutes if c.open_time > decided)
    assert again.result.exit_time == exit_candle.close_time


def test_prior_median_ranges_use_only_earlier_candles() -> None:
    rows = candles(Timeframe.M15, 200, 15)
    medians = prior_median_ranges(rows)
    assert rows[95].close_time not in medians
    ranges = sorted(c.high - c.low for c in rows[:96])
    assert medians[rows[96].close_time] == (ranges[47] + ranges[48]) / 2


def opened() -> TradeSimulator:
    sim = TradeSimulator(order(expires_at=START + timedelta(days=1)))
    sim.on_candle(bar(0, "100.50", "101", "100", "100.80"))  # Entry 100.53, risk 2.00.
    return sim


def test_the_checks_fire_once_each_and_respect_their_gaps() -> None:
    counts = CheckCounts()
    sim = opened()
    quiet: dict[datetime, D] = {}
    checks = TradeChecks(counts, quiet)
    high = bar(1, "102", "103", "101.9", "102.9")
    checks.on_close(sim, high, D(103), improved=True)
    for index in range(2, 11):
        checks.on_close(sim, bar(index, "102.8", "102.9", "102.7", "102.8"), D(103), False)
    assert counts.checks["stall past +1R"] == 1, "once until a new best"
    rejected = bar(11, "103", "103.6", "102.4", "102.5")  # 0.4 short of 104, 1.1 back.
    checks.on_close(sim, rejected, D("103.6"), improved=True)
    checks.on_close(sim, rejected, D("103.6"), improved=False)
    assert counts.checks["rejected near a target"] == 1, "once per target"
    jumpy = TradeChecks(counts, {bar(12, "1", "1", "1", "1").close_time: D("0.5")})
    wide = bar(12, "102", "103", "101", "102.5")
    jumpy.on_close(sim, wide, D("103.6"), improved=False)
    jumpy.on_close(sim, wide, D("103.6"), improved=False)
    assert counts.checks["volatility jump"] == 1, "at most once every 8 candles"
    assert counts.trades == 2 and counts.open_candles == 14


def test_a_stricter_bootstrap_level_widens_the_interval_and_95_is_unchanged() -> None:
    values = [float(i % 7) - 2.5 for i in range(300)]
    default = bootstrap_interval(values)
    strict = bootstrap_interval(values, 1 - 0.05 / 9)
    assert default == bootstrap_interval(values, 0.95)
    assert default is not None and strict is not None
    assert strict[0] < default[0] and strict[1] > default[1]


def test_the_report_renders_and_applies_the_decision_rule() -> None:
    """Made-up pairs, not market data: only the report and the rule are under test."""
    from trading_intel.entrypoints import exit_rules_backtest as study

    result = study.Study(replayed=12, mismatched=0)
    for strategy in study.STRATEGIES:
        for coin in study.COINS:
            for level in study.LEVELS:
                for own in (-1.0, 2.0):
                    better = {"breakeven": own + 0.2, "stall_exit": own - 0.1, "swing_trail": own}
                    acted = {rule: True for rule in study.RULES}
                    result.pairs.append(study.Paired(strategy, coin, level, own, better, acted))
    assert study.verdict(result, "daily_trend", "breakeven").passes
    assert not study.verdict(result, "daily_trend", "stall_exit").passes
    text = study.render(result)
    assert "**`breakeven` is adopted**" in text and "Simulated results" in text
    void = study.render(study.Study(replayed=3, mismatched=1))
    assert "**Void.**" in void
