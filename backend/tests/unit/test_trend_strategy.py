"""Daily trend following and its trailing exit. All candles are synthetic."""

from datetime import timedelta
from decimal import Decimal

from tests.quant_data import START, candle
from tests.unit.test_backtesting import INSTRUMENT, RULES
from trading_intel.backtesting.benchmarks import RandomDailyEntries
from trading_intel.backtesting.engine import BacktestEngine
from trading_intel.domain.candles import ClosedCandle, Timeframe
from trading_intel.domain.signals import Action, Side
from trading_intel.trade_signals.trend_strategy import DailyTrendStrategy, TrendParameters

TICK = Decimal("0.01")
# Flat for 25 days, a breakout, a steady climb to 115, then a fall.
PATH = [100.0] * 25 + [101.0 + i for i in range(15)] + [112.0 - 3 * i for i in range(10)]


def daily(closes: list[float]) -> list[ClosedCandle]:
    rows, previous = [], closes[0]
    for index, close in enumerate(closes):
        low, high = min(previous, close) - 0.5, max(previous, close) + 0.5
        rows.append(candle(index, previous, high, low, close, timeframe=Timeframe.D1))
        previous = close
    return rows


def hourly(closes: list[float]) -> list[ClosedCandle]:
    """Each day walks in a straight line from the previous close, with deep liquidity."""
    rows, previous = [], closes[0]
    for day, close in enumerate(closes):
        for hour in range(24):
            start = previous + (close - previous) * hour / 24
            end = previous + (close - previous) * (hour + 1) / 24
            low, high = min(start, end) - 0.2, max(start, end) + 0.2
            rows.append(candle(day * 24 + hour, start, high, low, end, 100000.0, Timeframe.H1))
        previous = close
    return rows


DAYS = daily(PATH)


def test_a_close_above_the_20_day_range_is_a_buy_with_a_2_atr_stop() -> None:
    strategy = DailyTrendStrategy(DAYS, TICK)
    decision = strategy.decide(DAYS[25].close_time)
    assert decision.action is Action.BUY
    proposal = decision.proposal
    assert proposal is not None and decision.setup_atr is not None
    expected = (proposal.entry - 2 * decision.setup_atr).quantize(TICK, "ROUND_FLOOR")
    assert proposal.stop == expected
    risk = proposal.entry - proposal.stop
    assert proposal.targets == ((proposal.entry + 10 * risk).quantize(TICK),)


def test_inside_the_range_there_is_no_trade() -> None:
    strategy = DailyTrendStrategy(DAYS, TICK)
    assert strategy.decide(DAYS[24].close_time).action is Action.NO_TRADE


def test_a_close_below_the_range_is_a_sell() -> None:
    falling = daily([100.0] * 25 + [98.0])
    decision = DailyTrendStrategy(falling, TICK).decide(falling[25].close_time)
    assert decision.action is Action.SELL


def test_a_short_cap_never_goes_below_the_lowest_price() -> None:
    """Regression: on a cheap, volatile coin a short's 10R cap fell below zero (2026-11-07)."""
    swings = daily([10.0 + (3.0 if i % 2 else -3.0) for i in range(25)] + [6.0])
    decision = DailyTrendStrategy(swings, TICK).decide(swings[-1].close_time)
    proposal = decision.proposal
    assert decision.action is Action.SELL and proposal is not None
    assert proposal.entry - 10 * (proposal.stop - proposal.entry) < 0
    assert proposal.targets == (TICK,)


def test_the_stop_trails_the_10_day_extreme_and_never_loosens() -> None:
    strategy = DailyTrendStrategy(DAYS, TICK)
    peak = DAYS[39].close_time
    level = strategy.trailing_stop(peak, Side.LONG, Decimal("99.00"))
    assert level == Decimal("104.50")  # Lowest low of days 30 to 39.
    assert strategy.trailing_stop(peak, Side.LONG, Decimal("110.00")) is None


def test_the_engine_exits_on_the_trailed_stop_after_the_peak() -> None:
    result = BacktestEngine(
        INSTRUMENT,
        RULES,
        hourly(PATH),
        DAYS,
        DAYS,
        DAYS,
        strategy=DailyTrendStrategy(DAYS, TICK),
        skip_signals_in_trade=True,
    ).run(START, START + timedelta(days=len(PATH)))
    [trade] = result.trades
    outcome = trade.result
    assert outcome.exit_reason == "stop"
    assert outcome.net_pnl > 0
    assert outcome.exit_time is not None and outcome.exit_time > DAYS[39].close_time
    assert outcome.exit_price is not None and outcome.entry_price is not None
    assert outcome.exit_price > outcome.entry_price  # The stop had trailed above the entry.


def test_random_entries_keep_the_same_stops_and_are_seeded() -> None:
    window = (DAYS[22].close_time, DAYS[-1].close_time)
    first = RandomDailyEntries(DAYS, TICK, TrendParameters(), 3, 7, window)
    again = RandomDailyEntries(DAYS, TICK, TrendParameters(), 3, 7, window)
    decisions = [first.decide(day.close_time) for day in DAYS]
    trades = [d for d in decisions if d.action in (Action.BUY, Action.SELL)]
    assert len(trades) == 3
    assert [again.decide(day.close_time).action for day in DAYS] == [d.action for d in decisions]
    assert all(d.proposal is not None and d.proposal.invalidation_conditions for d in trades)
