"""The signal score's conditions and the study's checks, on synthetic candles and trades."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from tests.quant_data import START, candle
from trading_intel.backtesting.metrics import difference_interval
from trading_intel.domain.candles import Timeframe
from trading_intel.domain.signals import Side
from trading_intel.entrypoints.signal_score import (
    Scored,
    checks,
    gap_of,
    sizing,
    years_above,
)
from trading_intel.technical_analysis.series import CandleSeries
from trading_intel.trade_signals.pattern_strategy import STRATEGY_NAME as PATTERN_NAME
from trading_intel.trade_signals.signal_score import (
    Conditions,
    FundingView,
    LongTermTrend,
    VolumeView,
)
from trading_intel.trade_signals.trend_strategy import STRATEGY_NAME as TREND_NAME


def days(closes: list[float]) -> CandleSeries:
    rows = [candle(i, c, c + 1, c - 1, c, timeframe=Timeframe.D1) for i, c in enumerate(closes)]
    return CandleSeries.of(rows)


def test_the_long_term_trend_needs_200_closes_and_reads_the_last_closed_day() -> None:
    series = days([100 + i for i in range(199)] + [50])
    view = LongTermTrend(series)
    assert view.agrees(series.close_time[198], Side.LONG) is None, "199 closes are too few"
    last = series.close_time[199]
    assert view.agrees(last, Side.LONG) is False
    assert view.agrees(last, Side.SHORT) is True
    # One millisecond before the last day closes, it cannot be read yet.
    assert view.agrees(last - timedelta(milliseconds=1), Side.LONG) is None


def test_a_later_candle_never_changes_an_earlier_reading() -> None:
    closes = [100 + i for i in range(230)]
    moment = days(closes).close_time[210]
    changed = closes[:211] + [5.0] * 19
    assert LongTermTrend(days(closes)).agrees(moment, Side.LONG) is True
    assert LongTermTrend(days(changed)).agrees(moment, Side.LONG) is True


def test_volume_confirms_at_or_above_the_mean_of_the_20_before() -> None:
    volumes = [10.0] * 20 + [10.0, 9.0]
    rows = [candle(i, 100, 101, 99, 100, v) for i, v in enumerate(volumes)]
    series = CandleSeries.of(rows)
    view = VolumeView(series)
    assert view.confirms(series.close_time[19]) is None, "fewer than 20 candles before"
    assert view.confirms(series.close_time[20]) is True, "equal to the mean counts"
    assert view.confirms(series.close_time[21]) is False
    assert view.confirms(START) is None, "not a setup candle's close"


def rates(values: list[str], start: datetime = START) -> list[tuple[datetime, D]]:
    return [(start + timedelta(hours=8 * i), D(value)) for i, value in enumerate(values)]


def test_funding_at_its_usual_level_is_for_both_sides() -> None:
    """Regression guard: float means drift above 0.0001 and would turn ties against longs."""
    history = rates(["0.0001"] * 300)
    moment = history[-1][0]
    view = FundingView(history)
    assert view.agrees(moment, Side.LONG) is True
    assert view.agrees(moment, Side.SHORT) is True


def test_crowded_funding_is_against_longs_and_for_shorts() -> None:
    history = rates(["0.0001"] * 297 + ["0.0005"] * 3)
    moment = history[-1][0]
    view = FundingView(history)
    assert view.agrees(moment, Side.LONG) is False
    assert view.agrees(moment, Side.SHORT) is True
    # Before those three were paid, the last day was usual again.
    assert view.agrees(history[-4][0], Side.LONG) is True


def test_funding_is_unknown_without_90_days_or_a_recent_rate() -> None:
    history = rates(["0.0001"] * 300)
    view = FundingView(history)
    assert view.agrees(history[200][0], Side.LONG) is None, "under 90 days stored"
    gap = history[-1][0] + timedelta(days=2)
    assert view.agrees(gap, Side.LONG) is None, "nothing paid in the last 24 hours"
    assert FundingView([]).agrees(START, Side.LONG) is None


def test_two_conditions_against_make_a_signal_weak() -> None:
    assert Conditions(True, True, False, True).weak is False
    assert Conditions(True, False, False, True).weak is True
    assert Conditions(True, None, False, False).weak is None, "unknown is never scored"


def test_bitcoins_own_trades_skip_the_bitcoin_condition() -> None:
    own = Conditions(False, None, True, True, bitcoin_applies=False)
    assert own.known and own.weak is False
    assert Conditions(False, None, False, True, bitcoin_applies=False).weak is True


def test_the_difference_interval_is_seeded_and_holds_the_difference() -> None:
    first, second = [1.0, 2.0, 3.0, 0.5], [0.0, -1.0, 0.5, -0.5]
    interval = difference_interval(first, second)
    assert interval == difference_interval(first, second)
    assert interval is not None and interval[0] < 2.0 - (-0.25) < interval[1]
    assert difference_interval([1.0], second) is None


STRONG = Conditions(True, True, True, True)
WEAK = Conditions(False, False, True, True)
UNKNOWN = Conditions(True, None, True, True)
COIN_CYCLE = ("BTCUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT")


def row(
    strategy: str, coin: str, side: Side, year: int, r: float, conditions: Conditions
) -> Scored:
    at = datetime(year, 3, 1, tzinfo=UTC) + timedelta(hours=len(coin) * 7 + int(r * 10))
    return Scored(strategy, coin, side, at, at + timedelta(days=3), r, conditions)


def history(weak_pattern_r: float = -0.5) -> list[Scored]:
    rows = []
    for year in range(2020, 2026):
        for strategy in (TREND_NAME, PATTERN_NAME):
            for side in Side:
                for index, coin in enumerate(COIN_CYCLE):
                    weak_r = weak_pattern_r if strategy == PATTERN_NAME else -0.5
                    rows.append(row(strategy, coin, side, year, 1.0 + index / 10, STRONG))
                    rows.append(row(strategy, coin, side, year, weak_r - index / 10, WEAK))
    return rows


def test_signals_with_an_unknown_condition_are_in_neither_group() -> None:
    gap = gap_of([row(TREND_NAME, "SOLUSDT", Side.LONG, 2021, 1.0, UNKNOWN)])
    assert gap.strong == [] and gap.weak == [] and gap.difference is None


def test_a_year_with_too_few_trades_does_not_count() -> None:
    rows = [r for r in history() if r.signal_time.year != 2020]
    rows.append(row(TREND_NAME, "SOLUSDT", Side.LONG, 2020, 3.0, STRONG))
    rows.append(row(TREND_NAME, "SOLUSDT", Side.LONG, 2020, -1.0, WEAK))
    assert years_above(rows) == 5


def test_scored_sizing_halves_weak_signals_and_weighs_by_share() -> None:
    rows = [
        row(TREND_NAME, "SOLUSDT", Side.LONG, 2021, 2.0, STRONG),
        row(PATTERN_NAME, "SOLUSDT", Side.LONG, 2022, 2.0, STRONG),
        row(TREND_NAME, "SOLUSDT", Side.LONG, 2023, -1.0, WEAK),
    ]
    assert sizing(rows, with_score=False).total == pytest.approx(2.0 + 1.0 - 1.0)
    assert sizing(rows, with_score=True).total == pytest.approx(2.0 + 1.0 - 0.5)
    assert sizing(rows, with_score=True).drawdown == pytest.approx(0.5)


def test_every_check_passes_when_strong_beats_weak_everywhere() -> None:
    found = checks(history())
    assert [check.passed for check in found] == [True] * 6


def test_the_score_fails_when_one_strategy_reverses() -> None:
    found = checks(history(weak_pattern_r=3.0))
    assert not found[1].passed, "the pattern's weak signals did better"
    assert not all(check.passed for check in found)
