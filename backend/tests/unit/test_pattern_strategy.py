"""The pattern breakout strategy and its random benchmark. All candles are synthetic."""

from decimal import Decimal

from tests.quant_data import candle
from trading_intel.backtesting.benchmarks import ExitTemplate, RandomTrendEntries, exit_template
from trading_intel.domain.candles import ClosedCandle, Timeframe
from trading_intel.domain.signals import Action, Side
from trading_intel.trade_signals.pattern_strategy import PatternParameters, PatternStrategy

TICK = Decimal("0.01")


def waves(timeframe: Timeframe, up: bool = True, count: int = 8) -> list[ClosedCandle]:
    """Trending waves that all close before the 1H series starts."""
    sign = 1 if up else -1
    closes: list[float] = []
    level = 1000.0
    for _ in range(count):
        closes += [level + sign * step for step in (2, 4, 6, 8, 10, 12)]
        closes += [level + sign * step for step in (10, 8, 6)]
        level += sign * 6
    closes.append(level + sign * 12)
    rows: list[ClosedCandle] = []
    previous = closes[0]
    for index, close in enumerate(closes):
        low, high = min(previous, close) - 0.1, max(previous, close) + 0.1
        rows.append(candle(index - len(closes), previous, high, low, close, timeframe=timeframe))
        previous = close
    return rows


def flag_hours() -> list[ClosedCandle]:
    """A quiet base, a steep pole, a shallow pullback and a close above the pole."""
    closes = [100.0 + 0.1 * (i % 2) for i in range(40)]
    closes += [102, 104, 106, 108, 110, 109.4, 108.6, 107.8, 107.2, 109.5, 112]
    rows: list[ClosedCandle] = []
    previous = closes[0]
    for index, close in enumerate(closes):
        low, high = min(previous, close) - 0.2, max(previous, close) + 0.2
        rows.append(candle(index, previous, high, low, close, timeframe=Timeframe.H1))
        previous = close
    return rows


HOURS = flag_hours()
BREAKOUT = HOURS[-1].close_time


def strategy(
    up: bool = True, hours: list[ClosedCandle] = HOURS, **options: object
) -> PatternStrategy:
    return PatternStrategy(
        hours,
        waves(Timeframe.H4, up),
        waves(Timeframe.D1, up),
        TICK,
        PatternParameters(**options),  # type: ignore[arg-type]
    )


def test_a_bull_flag_with_both_trends_up_is_a_buy() -> None:
    decision = strategy().decide(BREAKOUT)
    assert decision.action is Action.BUY
    assert decision.reasons == ("bull_flag breakout with 4H and 1D up",)
    proposal = decision.proposal
    assert proposal is not None and decision.setup_atr is not None
    flag_low = Decimal("107.00")
    assert proposal.stop == (flag_low - Decimal("0.25") * decision.setup_atr).quantize(
        TICK, "ROUND_FLOOR"
    )
    risk = proposal.entry - proposal.stop
    assert proposal.targets and all(t - proposal.entry >= 2 * risk for t in proposal.targets)
    assert list(proposal.targets) == sorted(proposal.targets)
    assert decision.catalogue is not None
    kinds = {level.kind for level in decision.catalogue.levels}
    assert {"measured_move", "pattern_invalidation"} <= kinds


def test_the_same_breakout_against_the_higher_trend_is_no_trade() -> None:
    decision = strategy(up=False).decide(BREAKOUT)
    assert decision.action is Action.NO_TRADE
    assert decision.reasons == ("bullish breakout against the trend: 4H down, 1D down",)
    assert decision.patterns and decision.patterns[0].pattern_type == "bull_flag"


def test_no_breakout_means_no_trade() -> None:
    decision = strategy().decide(HOURS[-3].close_time)
    assert decision.action is Action.NO_TRADE
    assert decision.reasons == ("no pattern breakout",)


def test_trial_two_needs_a_confirming_candle() -> None:
    assert strategy(require_candle=True, candle_window=0).decide(BREAKOUT).action is Action.NO_TRADE
    confirmed = strategy(require_candle=True).decide(BREAKOUT)
    if confirmed.action is Action.BUY:
        assert len(confirmed.patterns) == 2
        assert confirmed.patterns[1].direction is confirmed.patterns[0].direction


def test_a_decision_is_the_same_without_later_candles() -> None:
    later = [*HOURS]
    for index in range(len(HOURS), len(HOURS) + 30):
        close = 112.0 - (index - len(HOURS)) * 0.5
        later.append(
            candle(index, close + 0.5, close + 0.7, close - 0.2, close, timeframe=Timeframe.H1)
        )
    short, long = strategy(hours=HOURS).decide(BREAKOUT), strategy(hours=later).decide(BREAKOUT)
    assert short.action is long.action is Action.BUY
    assert short.proposal == long.proposal


def test_exit_templates_measure_stops_in_atr_and_targets_in_r() -> None:
    template = exit_template(Decimal(100), Decimal(98), (Decimal(104), Decimal(106)), Decimal(1))
    assert template == ExitTemplate(stop_atr=2.0, target_r=(2.0, 3.0))


def test_random_entries_are_seeded_and_follow_the_trend() -> None:
    base = strategy()
    template = ExitTemplate(stop_atr=2.0, target_r=(2.0, 3.0))
    start, end = HOURS[20].close_time, BREAKOUT
    first = RandomTrendEntries(base, [template], 5, seed=1, start=start, end=end)
    again = RandomTrendEntries(base, [template], 5, seed=1, start=start, end=end)
    assert first.planned == again.planned and len(first.planned) == 5
    for moment in first.planned:
        decision = first.decide(moment)
        assert decision.action is Action.BUY
        proposal = decision.proposal
        assert proposal is not None and proposal.side is Side.LONG
        risk = proposal.entry - proposal.stop
        assert proposal.targets[0] - proposal.entry == 2 * risk
        # Regression: without one, the risk engine rejected every benchmark trade.
        assert proposal.invalidation_conditions
    assert first.decide(HOURS[5].close_time).action is Action.NO_TRADE
