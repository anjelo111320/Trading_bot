"""The 4H gap and 15M CHoCH strategy (docs/35). All candles are synthetic test data."""

from collections import Counter
from datetime import timedelta
from decimal import Decimal

from tests.quant_data import candle
from tests.unit.test_backtesting import INSTRUMENT, RULES
from trading_intel.backtesting.benchmarks import ExitTemplate, RandomTrendEntries
from trading_intel.backtesting.engine import BacktestResult
from trading_intel.backtesting.report import STATEMENT
from trading_intel.domain.candles import ClosedCandle, Timeframe
from trading_intel.domain.signals import Action, EntryType, Side
from trading_intel.entrypoints.coin_replication import COINS
from trading_intel.entrypoints.fvg_choch_backtest import CoinRun, decision_lines, render, run_coin
from trading_intel.entrypoints.pattern_backtest import SEEDS, START, STRESS, Inputs
from trading_intel.trade_signals.fvg_choch_strategy import FvgChochStrategy

TICK = Decimal("0.01")
MIRROR = 300.0

# A 4H rise that breaks a swing high, so the 4H trend is up. Its last leg leaves bullish gaps,
# the newest from 106.10 to 107.90. Every candle closes before the 15M candles start.
FOUR_HOUR_CLOSES = [100, 101, 102, 103, 104, 103, 102, 101, 102, 104, 106, 108, 110]
# 15M: a down-trend that pulls back into that gap, low 107.20, then a rally that leaves a 15M
# gap from 110.30 to 110.90 and closes above the last swing high at 111.70: a bullish CHoCH.
FALL = [114, 113.6, 113.2, 112.8, 112.4, 112.0, 112.4, 112.8, 113.0, 112.6, 112.2, 111.8,
        111.4, 111.0, 110.6, 111.0, 111.4, 111.6, 111.2, 110.8, 110.4, 110.0, 109.6, 109.2,
        108.8, 108.4, 108.0, 107.6, 107.3]  # fmt: skip
RALLY = [107.6, 108.0, 108.6, 109.4, 110.2, 111.0, 111.8]


def rows(
    closes: list[float],
    timeframe: Timeframe,
    start: int = 0,
    wicks: list[float] | None = None,
) -> list[ClosedCandle]:
    found: list[ClosedCandle] = []
    previous = closes[0]
    for offset, close in enumerate(closes):
        wick = wicks[offset] if wicks else 0.1
        low, high = min(previous, close) - wick, max(previous, close) + wick
        found.append(candle(start + offset, previous, high, low, close, timeframe=timeframe))
        previous = close
    return found


def four_hours(shift: float = 0.0) -> list[ClosedCandle]:
    closes = [c + shift for c in FOUR_HOUR_CLOSES]
    return rows(closes, Timeframe.H4, start=-len(closes))


def quarters(shift: float = 0.0, rally_wick: float = 0.1) -> list[ClosedCandle]:
    closes = [c + shift for c in FALL + RALLY]
    wicks = [0.1] * len(FALL) + [rally_wick] * len(RALLY)
    return rows(closes, Timeframe.M15, wicks=wicks)


def mirrored(candles: list[ClosedCandle]) -> list[ClosedCandle]:
    """Prices reflected, so a rise becomes a fall. Highs and lows swap."""

    def flip(value: Decimal) -> Decimal:
        return Decimal(str(MIRROR)) - value

    return [
        c.model_copy(
            update={
                "open": flip(c.open),
                "high": flip(c.low),
                "low": flip(c.high),
                "close": flip(c.close),
            }
        )
        for c in candles
    ]


def strategy(
    setup: list[ClosedCandle] | None = None, fours: list[ClosedCandle] | None = None
) -> FvgChochStrategy:
    return FvgChochStrategy(setup or quarters(), fours or four_hours(), TICK)


def test_a_choch_from_inside_an_open_4h_gap_places_a_limit_at_the_15m_gap() -> None:
    setup = quarters()
    decision = strategy(setup).decide(setup[-1].close_time)
    assert decision.action is Action.BUY, decision.reasons
    proposal = decision.proposal
    assert proposal is not None and decision.setup_atr is not None
    assert proposal.entry_type is EntryType.LIMIT
    assert proposal.entry == Decimal("110.90")
    assert proposal.stop < Decimal("107.20")
    risk = proposal.entry - proposal.stop
    assert all(target - proposal.entry >= 2 * risk for target in proposal.targets)
    assert proposal.expiry_candles == 8
    assert proposal.entry < Decimal(str(float(setup[-1].close)))
    kinds = [(p.pattern_type, p.evidence.get("timeframe")) for p in decision.patterns]
    assert kinds == [("fair_value_gap", "4h"), ("choch", "15m"), ("fair_value_gap", "15m")]
    zone = decision.patterns[0]
    assert (zone.zone_low, zone.zone_high) == (106.1, 107.9)


def test_a_short_mirrors_the_long() -> None:
    setup = mirrored(quarters())
    decision = strategy(setup, mirrored(four_hours())).decide(setup[-1].close_time)
    assert decision.action is Action.SELL, decision.reasons
    assert decision.proposal is not None
    assert decision.proposal.side is Side.SHORT
    assert decision.proposal.entry == Decimal("189.10")
    assert decision.proposal.stop > Decimal("192.80")


def test_no_trade_against_the_4h_trend() -> None:
    setup = quarters()
    decision = strategy(setup, mirrored(four_hours())).decide(setup[-1].close_time)
    assert decision.action is Action.NO_TRADE
    assert decision.reasons == ("CHoCH against the 4H trend: 4H down",)


def test_no_trade_when_the_pullback_stops_above_the_4h_gap() -> None:
    setup = quarters(shift=3.0)
    decision = strategy(setup, four_hours()).decide(setup[-1].close_time)
    assert decision.reasons == ("the pullback did not reach an open 4H gap",)


def test_a_4h_gap_already_filled_does_not_count() -> None:
    setup = quarters()
    first = setup[0]
    setup[0] = first.model_copy(update={"low": Decimal("106.00")})
    decision = strategy(setup).decide(setup[-1].close_time)
    assert decision.reasons == ("the pullback did not reach an open 4H gap",)


def test_a_4h_gap_older_than_30_days_does_not_count() -> None:
    setup = quarters()
    later = timedelta(days=31)
    days_later = [
        c.model_copy(update={"open_time": c.open_time + later, "close_time": c.close_time + later})
        for c in setup
    ]
    decision = strategy(days_later).decide(days_later[-1].close_time)
    assert decision.reasons == ("the pullback did not reach an open 4H gap",)


def test_no_trade_without_a_15m_gap_in_the_move() -> None:
    setup = quarters(rally_wick=0.5)
    decision = strategy(setup).decide(setup[-1].close_time)
    assert decision.reasons == ("no open 15M gap in the move",)


def test_only_a_choch_candle_can_trade() -> None:
    setup = quarters()
    decision = strategy(setup).decide(setup[-2].close_time)
    assert decision.reasons == ("no CHoCH on this 15M candle",)


def test_decisions_never_depend_on_later_candles() -> None:
    setup = quarters()
    full = strategy(setup)
    for end in range(10, len(setup) + 1):
        moment = setup[end - 1].close_time
        assert strategy(setup[:end]).decide(moment) == full.decide(moment)


def test_the_random_benchmark_reads_the_4h_trend() -> None:
    setup = quarters()
    base = strategy(setup)
    template = ExitTemplate(stop_atr=1.0, target_r=(2.0,))
    start, end = setup[0].close_time, setup[-1].close_time
    entries = RandomTrendEntries(base, [template], 5, seed=1, start=start, end=end)
    assert len(entries.planned) == 5
    for moment in entries.planned:
        decision = entries.decide(moment)
        assert decision.action is Action.BUY
        assert decision.proposal is not None
        assert decision.proposal.entry_type is EntryType.MARKET


def test_the_study_runs_end_to_end_and_reports_its_decision() -> None:
    """Synthetic candles moved into the study window, with a limit that fills and a rally."""
    after = [111.5, 111.0, 112.0, 113.5, 115.0, 116.5, 118.0, 119.5, 121.0, 122.5, 124.0]
    wicks = [0.1] * (len(FALL) + len(RALLY)) + [1.0] + [0.1] * (len(after) - 1)
    closes = FALL + RALLY + after
    moved = START + timedelta(days=30) - quarters()[0].open_time

    def shift(candles: list[ClosedCandle]) -> list[ClosedCandle]:
        return [
            c.model_copy(
                update={"open_time": c.open_time + moved, "close_time": c.close_time + moved}
            )
            for c in candles
        ]

    inputs = Inputs(
        symbol="BTCUSDT",
        instrument=INSTRUMENT,
        rules=RULES,
        fills=shift(rows(closes, Timeframe.M15, wicks=wicks)),
        hours=[],
        four_hours=shift(four_hours()),
        days=[],
        funding=[],
    )
    coin = run_coin(inputs)
    assert coin.funnel["proposed"] == 1
    [trade] = coin.results["1"].trades
    assert trade.order.entry_type is EntryType.LIMIT
    assert trade.result.entry_price == Decimal("110.90")
    assert len(coin.benchmark) == len(SEEDS)
    text = render([coin])
    assert "## Decision" in text and STATEMENT in text


def test_no_trades_is_a_rejection() -> None:
    empty = {level: BacktestResult() for level in STRESS}
    lines = decision_lines([CoinRun(symbol, empty, Counter(), 0) for symbol in COINS])
    assert "**Rejected**" in lines[0]
