from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from typing import Any

import pytest

from tests.quant_data import START, candle
from trading_intel.backtesting.engine import AsOfCandles, BacktestEngine, CostModel
from trading_intel.backtesting.metrics import (
    ClosedTrade,
    bootstrap_interval,
    compute_metrics,
    daily_returns,
    maximum_drawdown,
)
from trading_intel.backtesting.report import STATEMENT, render
from trading_intel.backtesting.windows import (
    HOLDOUT_START,
    HoldoutViolationError,
    refuse_holdout,
    walk_forward,
)
from trading_intel.domain.candles import ClosedCandle, Timeframe
from trading_intel.domain.instruments import Instrument, InstrumentRules, InstrumentType
from trading_intel.trade_signals.baseline import BaselineParameters

INSTRUMENT = Instrument(
    id=1,
    symbol="TESTUSDT",
    instrument_type=InstrumentType.LINEAR_PERPETUAL,
    base_asset="TEST",
    quote_asset="USDT",
    settle_asset="USDT",
)
RULES = InstrumentRules(
    status="TRADING",
    tick_size=D("0.01"),
    lot_step=D("0.001"),
    min_qty=D("0.001"),
    max_qty=D(100000),
    min_notional=D(5),
    maintenance_margin_fraction=D("0.025"),
    raw={},
)


def wave_prices(count: int, seed: int = 0) -> list[float]:
    """A rising series with pullbacks, so breaks of structure occur."""
    prices = []
    for index in range(count):
        cycle = index % 40
        swing = cycle * 1.2 if cycle < 28 else (40 - cycle) * 2.4
        prices.append(1000 + index * 0.5 + swing + (seed % 3) * 0.1)
    return prices


def candles(timeframe: Timeframe, count: int, scale: int = 1) -> list[ClosedCandle]:
    prices = wave_prices(count * scale)[::scale]
    rows = []
    previous = prices[0]
    for index, price in enumerate(prices):
        rows.append(
            candle(
                index,
                previous,
                max(previous, price) + 0.5,
                min(previous, price) - 0.5,
                price,
                1000.0,
                timeframe,
            )
        )
        previous = price
    return rows


def engine(
    minutes: list[ClosedCandle] | None = None,
    setup: list[ClosedCandle] | None = None,
    **options: Any,
) -> BacktestEngine:
    options.setdefault("parameters", BaselineParameters(min_adx=0))
    return BacktestEngine(
        INSTRUMENT,
        RULES,
        minutes if minutes is not None else candles(Timeframe.M1, 6000),
        setup if setup is not None else candles(Timeframe.M15, 400, 15),
        candles(Timeframe.H1, 110, 60),
        candles(Timeframe.H4, 30, 240),
        **options,
    )


FAR_END = START + timedelta(days=10)


def test_research_cannot_touch_the_holdout() -> None:
    with pytest.raises(HoldoutViolationError):
        refuse_holdout(HOLDOUT_START - timedelta(days=1), HOLDOUT_START + timedelta(minutes=1))


def test_research_up_to_the_holdout_is_allowed() -> None:
    refuse_holdout(HOLDOUT_START - timedelta(days=90), HOLDOUT_START)


def test_a_holdout_run_cannot_start_early() -> None:
    with pytest.raises(HoldoutViolationError):
        refuse_holdout(HOLDOUT_START - timedelta(days=1), HOLDOUT_START, holdout_run=True)


def test_the_holdout_date_is_frozen() -> None:
    assert datetime(2025, 11, 1, tzinfo=UTC) == HOLDOUT_START


def test_walk_forward_gives_ordered_folds_that_stop_before_the_holdout() -> None:
    folds = walk_forward(datetime(2019, 9, 8, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC))
    assert len(folds) == 7  # BTC history. ETH starts later and gives six.
    for fold in folds:
        assert fold.train_end < fold.validate_start < fold.validate_end
        assert fold.validate_end < fold.test_start < fold.test_end
        assert fold.test_end <= HOLDOUT_START
    assert all(a.test_start < b.test_start for a, b in zip(folds, folds[1:], strict=False))


def test_as_of_access_cannot_reach_a_candle_that_has_not_closed() -> None:
    rows = candles(Timeframe.M15, 10, 15)
    access = AsOfCandles(rows)
    moment = rows[4].close_time
    assert access.closed_by(moment, 100) == rows[:5]
    assert access.closed_by(moment - timedelta(milliseconds=1), 100) == rows[:4]


def test_four_hour_value_changes_only_after_its_close() -> None:
    rows = candles(Timeframe.H4, 5, 240)
    access = AsOfCandles(rows)
    inside = rows[2].open_time + timedelta(hours=2)
    assert access.closed_by(inside, 10)[-1] is rows[1]


def test_the_engine_produces_trades_and_is_reproducible() -> None:
    first = engine().run(START, FAR_END)
    second = engine().run(START, FAR_END)
    assert first.decisions > 0
    assert first.metrics is not None
    assert [t.result.net_pnl for t in first.trades] == [t.result.net_pnl for t in second.trades]
    assert first.signals == second.signals


def test_corrupting_all_future_candles_changes_no_past_decision() -> None:
    """The look-ahead test for the whole replay."""
    cut = START + timedelta(days=2, hours=3)
    honest = engine().run(START, cut)
    minutes = candles(Timeframe.M1, 6000)
    setup = candles(Timeframe.M15, 400, 15)

    def corrupt(rows: list[ClosedCandle]) -> list[ClosedCandle]:
        return [
            c
            if c.close_time < cut
            else c.model_copy(update={"high": c.high * 2, "close": c.high * 2, "open": c.high * 2})
            for c in rows
        ]

    dishonest = engine(minutes=corrupt(minutes), setup=corrupt(setup)).run(START, cut)
    assert honest.signals == dishonest.signals
    assert honest.decisions == dishonest.decisions
    assert [t.signal_time for t in honest.trades] == [t.signal_time for t in dishonest.trades]
    assert [t.order for t in honest.trades] == [t.order for t in dishonest.trades]


def test_higher_costs_never_improve_the_result() -> None:
    plain = engine().run(START, FAR_END)
    stressed = engine(costs=CostModel().stressed("2")).run(START, FAR_END)
    assert plain.metrics is not None and stressed.metrics is not None
    if plain.trades and stressed.trades:
        assert (
            stressed.trades[0].result.net_pnl / stressed.trades[0].planned_risk
            <= plain.trades[0].result.net_pnl / plain.trades[0].planned_risk
        )


def test_cost_model_stress_scales_every_cost() -> None:
    double = CostModel().stressed("2")
    assert double.half_spread(D(10000)) == 2 * CostModel().half_spread(D(10000))
    assert double.slippage(D("0.1"), D(100)) == 2 * CostModel().slippage(D("0.1"), D(100))
    assert double.fees() == (D("0.0010"), D("0.0004"))


def closed(net: str, r: str, day: int = 0) -> ClosedTrade:
    at = START + timedelta(days=day)
    return ClosedTrade(at, at, D(net), D(r), D(1), D(net) + 1)


def test_metrics_by_hand() -> None:
    trades = [closed("200", "2", 0), closed("-100", "-1", 1), closed("100", "1", 2)]
    equity = [D(10000), D(10200), D(10100), D(10200)]
    metrics = compute_metrics(trades, equity, D(10000), 3)
    assert metrics.trades == 3
    assert metrics.net_pnl == 200
    assert metrics.win_rate == pytest.approx(2 / 3)
    assert metrics.expectancy_r == pytest.approx(2 / 3)
    assert metrics.profit_factor == 3
    assert metrics.total_return == pytest.approx(0.02)
    assert metrics.max_drawdown == pytest.approx(100 / 10200)


def test_no_trades_gives_empty_metrics_not_zeroes_pretending_to_be_results() -> None:
    metrics = compute_metrics([], [D(10000)], D(10000), 10)
    assert metrics.win_rate is None
    assert metrics.expectancy_r is None
    assert metrics.profit_factor is None


def test_drawdown_uses_the_peak_not_the_start() -> None:
    assert maximum_drawdown([D(100), D(200), D(100), D(150)]) == 0.5


def test_days_without_trades_count_as_flat_days() -> None:
    assert len(daily_returns([closed("100", "1", 0)], D(10000), 5)) == 5


def test_bootstrap_interval_is_seeded_and_contains_the_mean() -> None:
    values = [1.0, -1.0, 2.0, -1.0, 2.0, 1.0]
    first = bootstrap_interval(values)
    assert first == bootstrap_interval(values)
    assert first is not None
    assert first[0] <= sum(values) / len(values) <= first[1]


def test_the_report_is_labelled_as_simulated() -> None:
    result = engine().run(START, FAR_END)
    text = render("Test", result, ["Synthetic data only."])
    assert STATEMENT in text
    assert "Synthetic data only." in text
