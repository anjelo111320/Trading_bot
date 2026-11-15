"""The new-coin and 15M rule study (docs/42): the loose copy, reused decisions and the report."""

from datetime import UTC, datetime
from decimal import Decimal as D
from typing import Any

import pytest

from tests.unit.test_backtesting import candles
from trading_intel.backtesting import engine as engine_module
from trading_intel.backtesting.engine import WindowedBaseline
from trading_intel.domain.candles import Timeframe
from trading_intel.domain.signals import Action
from trading_intel.entrypoints.new_coin_study import (
    ALL_COINS,
    NEW_COINS,
    RULES,
    TESTED,
    Remembered,
    render,
)
from trading_intel.trade_signals.baseline import BaselineDecision, BaselineParameters


def windows() -> tuple[list[Any], list[Any], list[Any]]:
    return (
        candles(Timeframe.M15, 400, 15),
        candles(Timeframe.H1, 110, 60),
        candles(Timeframe.H4, 30, 240),
    )


def test_the_loose_copy_reads_a_break_in_its_last_three_candles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[int] = []

    def evaluate(*arguments: Any) -> BaselineDecision:
        seen.append(arguments[-1])
        return BaselineDecision(Action.NO_TRADE, datetime.now(UTC), ("test",))

    monkeypatch.setattr(engine_module, "evaluate", evaluate)
    setup, middle, higher = windows()
    moment = setup[-1].close_time
    WindowedBaseline(setup, middle, higher, D("0.01"), BaselineParameters()).decide(moment)
    WindowedBaseline(setup, middle, higher, D("0.01"), BaselineParameters(), break_window=3).decide(
        moment
    )
    assert seen == [1, 3]


def test_a_decision_is_worked_out_once_per_moment_and_reused() -> None:
    setup, middle, higher = windows()
    calls: list[datetime] = []

    class Counting(WindowedBaseline):
        def decide(self, moment: datetime) -> BaselineDecision | None:
            calls.append(moment)
            return super().decide(moment)

    rule = Remembered(Counting(setup, middle, higher, D("0.01"), BaselineParameters()))
    moment = setup[-1].close_time
    first = rule.decide(moment)
    assert rule.decide(moment) is first and calls == [moment]
    assert rule.timeframe is Timeframe.M15


def test_the_report_names_every_coin_and_decides_nothing_without_trades() -> None:
    runs = {
        (strategy, coin, level): []
        for strategy in TESTED
        for coin in NEW_COINS
        for level in ("1", "2")
    } | {
        (strategy, coin, level): []
        for strategy, _ in RULES
        for coin in ALL_COINS
        for level in ("1", "2")
    }
    text = render(runs)
    assert all(coin in text for coin in ALL_COINS)
    assert "- Left out, lost with 95% confidence: none." in text
    assert "trend_break_loose" in text and "fvg_choch" in text
