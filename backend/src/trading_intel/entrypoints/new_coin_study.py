"""Run the new-coin and 15M rule study once (docs/42).

Part A runs the three tested strategies on the four coins that trade untested (D052, D059).
Part B runs the 15M rule and its loose copy on all ten coins over two years, on 15-minute
fills, because no 1-minute history exists before the holdout. The rules and the decision rule
were pre-registered, and every window ends before the frozen holdout (D029).
"""

import argparse
import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Final

from trading_intel.backtesting.analysis import metrics_for
from trading_intel.backtesting.engine import (
    BacktestEngine,
    BacktestTrade,
    CostModel,
    WindowedBaseline,
)
from trading_intel.backtesting.metrics import Metrics
from trading_intel.backtesting.report import STATEMENT
from trading_intel.backtesting.windows import refuse_holdout
from trading_intel.domain.candles import Timeframe
from trading_intel.entrypoints import fvg_choch_backtest, pattern_backtest, trend_backtest
from trading_intel.entrypoints.coin_replication import COINS as TESTED_COINS
from trading_intel.entrypoints.pattern_backtest import END, REPORT_DIR, START, Inputs, load
from trading_intel.risk_management.allocation import loses_on_coin
from trading_intel.trade_signals.baseline import (
    LOOSE_NAME,
    LOOSE_WINDOW,
    BaselineDecision,
    BaselineParameters,
)
from trading_intel.trade_signals.baseline import STRATEGY_NAME as RULE_NAME
from trading_intel.trade_signals.fvg_choch_strategy import STRATEGY_NAME as FVG_NAME
from trading_intel.trade_signals.fvg_choch_strategy import FvgChochStrategy
from trading_intel.trade_signals.pattern_strategy import STRATEGY_NAME as PATTERN_NAME
from trading_intel.trade_signals.pattern_strategy import PatternStrategy
from trading_intel.trade_signals.trend_strategy import STRATEGY_NAME as TREND_NAME
from trading_intel.trade_signals.trend_strategy import DailyTrendStrategy

NEW_COINS: Final = ("ZECUSDT", "1000PEPEUSDT", "HYPEUSDT", "NEARUSDT")
ALL_COINS: Final = (*TESTED_COINS, *NEW_COINS)
TESTED: Final = (TREND_NAME, PATTERN_NAME, FVG_NAME)
RULES: Final = ((RULE_NAME, 1), (LOOSE_NAME, LOOSE_WINDOW))
RULE_START: Final = datetime(2023, 11, 1, tzinfo=UTC)
LEVELS: Final = ("1", "2")

Runs = dict[tuple[str, str, str], list[BacktestTrade]]


class Remembered:
    """A strategy's decision at each moment, worked out once and reused at 2x costs. A decision
    reads only candles closed by then, never costs, so it is the same at every cost level."""

    def __init__(self, strategy: WindowedBaseline) -> None:
        self._strategy = strategy
        self._decisions: dict[datetime, BaselineDecision | None] = {}

    @property
    def timeframe(self) -> Timeframe:
        return self._strategy.timeframe

    def decide(self, moment: datetime) -> BaselineDecision | None:
        if moment not in self._decisions:
            self._decisions[moment] = self._strategy.decide(moment)
        return self._decisions[moment]


def tested_runs(inputs: Inputs) -> Runs:
    """Part A: the three tested strategies at both cost levels, with their live parameters."""
    symbol, tick = inputs.symbol, inputs.rules.tick_size
    pattern = PatternStrategy(inputs.hours, inputs.four_hours, inputs.days, tick)
    trend = DailyTrendStrategy(inputs.days, tick, trend_backtest.PARAMETERS)
    fvg = FvgChochStrategy(inputs.fills, inputs.four_hours, tick, fvg_choch_backtest.PARAMETERS)
    runs: Runs = {}
    for level in LEVELS:
        runs[(TREND_NAME, symbol, level)] = trend_backtest.run(inputs, trend, level).trades
        runs[(PATTERN_NAME, symbol, level)] = pattern_backtest.run(inputs, pattern, level).trades
        runs[(FVG_NAME, symbol, level)] = fvg_choch_backtest.run(inputs, fvg, level).trades
    return runs


def rule_runs(inputs: Inputs) -> Runs:
    """Part B: the 15M rule and its loose copy at both cost levels, on 15-minute fills."""
    runs: Runs = {}
    for name, window in RULES:
        rule = Remembered(
            WindowedBaseline(
                inputs.fills, inputs.hours, inputs.four_hours, inputs.rules.tick_size,
                BaselineParameters(), break_window=window,
            )
        )  # fmt: skip
        for level in LEVELS:
            engine = BacktestEngine(
                inputs.instrument, inputs.rules, inputs.fills, inputs.fills, inputs.hours,
                inputs.four_hours, inputs.funding, costs=CostModel().stressed(level),
                strategy=rule, skip_signals_in_trade=True,
            )  # fmt: skip
            runs[(name, inputs.symbol, level)] = engine.run(RULE_START, END).trades
    return runs


def _days(start: datetime) -> int:
    return max((END - start).days, 1)


def _pooled(
    runs: Runs, strategy: str, coins: Sequence[str], start: datetime, level: str = "1"
) -> Metrics:
    trades = [trade for coin in coins for trade in runs.get((strategy, coin, level), [])]
    return metrics_for(trades, _days(start))


def _value(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:+.{digits}f}"


def _band(metrics: Metrics) -> str:
    interval = metrics.expectancy_interval
    return f"{interval[0]:+.2f} to {interval[1]:+.2f}" if interval else "n/a"


def _row(label: str, metrics: Metrics, doubled: Metrics, drawdown: str, note: str) -> str:
    rate = "n/a" if metrics.win_rate is None else f"{metrics.win_rate:.2f}"
    factor = "n/a" if metrics.profit_factor is None else f"{metrics.profit_factor:.2f}"
    return (
        f"| {label} | {metrics.trades} | {rate} | {_value(metrics.expectancy_r)} | "
        f"{_band(metrics)} | {factor} | {drawdown} | {_value(doubled.expectancy_r)} | {note} |"
    )


def _table(
    runs: Runs, strategy: str, coins: Sequence[str], start: datetime
) -> tuple[list[str], list[str], list[str]]:
    """A strategy's rows, with the coins it loses on with 95% confidence and the coins where
    its mean is below zero but its interval includes zero."""
    lines = [
        f"### {strategy}",
        "",
        "| Coin | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | "
        "Max drawdown | Expectancy at 2x costs | Note |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    lost: list[str] = []
    below: list[str] = []
    for coin in coins:
        metrics = metrics_for(runs[(strategy, coin, "1")], _days(start))
        doubled = metrics_for(runs[(strategy, coin, "2")], _days(start))
        notes = ["added untested"] if coin in NEW_COINS else []
        if loses_on_coin(metrics.expectancy_interval):
            notes.append("lost with 95% confidence")
            lost.append(coin)
        elif metrics.expectancy_r is not None and metrics.expectancy_r < 0:
            below.append(coin)
        drawdown = f"{metrics.max_drawdown:.1%}" if metrics.trades else "n/a"
        lines.append(_row(coin, metrics, doubled, drawdown, ", ".join(notes)))
    pooled = _pooled(runs, strategy, coins, start)
    doubled = _pooled(runs, strategy, coins, start, "2")
    lines += [_row(f"**{len(coins)} coins pooled**", pooled, doubled, "n/a", "pooled"), ""]
    return lines, lost, below


def render(runs: Runs) -> str:
    lines = [
        "# New Coins and the 15M Rule Study",
        "",
        STATEMENT,
        "",
        "Pre-registered in [42-NEW-COIN-STUDY.md](../42-NEW-COIN-STUDY.md) and run once. Each "
        "coin is a separate 10,000 account at 1% risk per trade.",
        "",
        f"## Part A: tested strategies on the new coins, {START:%Y-%m-%d} or the first candle "
        f"to {END:%Y-%m-%d}",
        "",
    ]
    left_out: list[str] = []
    listed: list[str] = []
    for strategy in TESTED:
        table, lost, below = _table(runs, strategy, NEW_COINS, START)
        lines += table
        left_out += [f"{strategy} on {coin}" for coin in lost]
        listed += [f"{strategy} on {coin}" for coin in below]
    lines += [
        f"## Part B: the 15M rule on all ten coins, {RULE_START:%Y-%m-%d} or the first candle "
        f"to {END:%Y-%m-%d}, on 15-minute fills",
        "",
    ]
    switch_off: list[str] = []
    for strategy, _ in RULES:
        table, lost, below = _table(runs, strategy, ALL_COINS, RULE_START)
        lines += table
        left_out += [f"{strategy} on {coin}" for coin in lost]
        listed += [f"{strategy} on {coin}" for coin in below]
        if loses_on_coin(_pooled(runs, strategy, ALL_COINS, RULE_START).expectancy_interval):
            switch_off.append(strategy)
    lines += [
        "## Decision",
        "",
        "Applied as pre-registered.",
        "",
        f"- Left out, lost with 95% confidence: {', '.join(left_out) or 'none'}.",
        "- Recommended to the owner to switch off on every coin, ten-coin interval below "
        f"zero: {', '.join(switch_off) or 'none'}.",
        f"- Mean below zero, interval includes zero, still trading: {', '.join(listed) or 'none'}.",
        "",
        "## Limits",
        "",
        "- HYPE has 5 months of history before the holdout, so its results are weak.",
        "- Part B fills on 15-minute candles, coarser than the 1-minute fills the 15M rule needs.",
        "- The coins move together, so pooled intervals are narrower than they should be.",
        "- The new coins were chosen in 2026 because they were trending then.",
        "- A pass is not proof of future profit.",
        "",
    ]
    return "\n".join(lines)


async def study() -> str:
    refuse_holdout(START, END)
    refuse_holdout(RULE_START, END)
    runs: Runs = {}
    for symbol in ALL_COINS:
        # One coin at a time, keeping only its trades, so memory stays small.
        inputs = await load(symbol)
        if symbol in NEW_COINS:
            runs.update(tested_runs(inputs))
        runs.update(rule_runs(inputs))
        print(f"{symbol} done", flush=True)
    return render(runs)


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    text = asyncio.run(study())
    (REPORT_DIR / "new-coin-study.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
