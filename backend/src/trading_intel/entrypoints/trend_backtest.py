"""Backtest the daily trend strategy on history from before the frozen holdout (docs/29)."""

import argparse
import asyncio
import statistics
from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from typing import Final

from trading_intel.backtesting.analysis import buy_and_hold, entered_between, group, metrics_for
from trading_intel.backtesting.benchmarks import RandomDailyEntries
from trading_intel.backtesting.engine import (
    BacktestEngine,
    BacktestResult,
    BacktestTrade,
    CostModel,
    Strategy,
)
from trading_intel.backtesting.metrics import Metrics
from trading_intel.backtesting.report import STATEMENT, metrics_table
from trading_intel.backtesting.windows import refuse_holdout, walk_forward
from trading_intel.entrypoints.pattern_backtest import END, REPORT_DIR, START, Inputs, load
from trading_intel.trade_signals.trend_strategy import (
    STRATEGY_NAME,
    STRATEGY_VERSION,
    DailyTrendStrategy,
    TrendParameters,
)

PARAMETERS: Final = TrendParameters()
SEEDS: Final = range(1, 21)
HEADER: Final = [
    "| | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Net P/L |",
    "|---|---|---|---|---|---|---|",
]


def _value(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _row(label: str, metrics: Metrics) -> str:
    interval = metrics.expectancy_interval
    band = f"{interval[0]:.2f} to {interval[1]:.2f}" if interval else "n/a"
    return (
        f"| {label} | {metrics.trades} | {_value(metrics.win_rate, 2)} | "
        f"{_value(metrics.expectancy_r)} | {band} | {_value(metrics.profit_factor, 2)} | "
        f"{metrics.net_pnl:.0f} |"
    )


def _days(start: datetime, end: datetime) -> int:
    return max((end - start).days, 1)


def run(inputs: Inputs, strategy: Strategy, stress: str = "1") -> BacktestResult:
    return BacktestEngine(
        inputs.instrument,
        inputs.rules,
        inputs.fills,
        inputs.days,
        inputs.days,
        inputs.days,
        inputs.funding,
        costs=CostModel().stressed(stress),
        strategy=strategy,
        skip_signals_in_trade=True,
    ).run(START, END)


def _year(trade: BacktestTrade) -> str:
    return f"{trade.signal_time:%Y}"


def render(inputs: Inputs, results: dict[str, BacktestResult], random: Sequence[Metrics]) -> str:
    base = results["1"]
    assert base.metrics is not None
    hold = buy_and_hold(inputs.days, START, END)
    exits = Counter(t.result.exit_reason for t in base.trades)
    lines = [
        f"# Daily Trend Backtest: {inputs.symbol} Perpetual",
        "",
        STATEMENT,
        "",
        f"Strategy `{STRATEGY_NAME}` version {STRATEGY_VERSION}, the Turtle System 1 rules, "
        "registered before any run in [29-TREND-STRATEGY.md](../29-TREND-STRATEGY.md). Period "
        f"{START:%Y-%m-%d} to {END:%Y-%m-%d}, before the frozen holdout.",
        "",
        "## Normal Costs",
        "",
        *metrics_table(base.metrics),
        "",
        f"Signals that reached the risk engine: {base.signals}. Exits: "
        + ", ".join(f"{reason} {count}" for reason, count in exits.most_common())
        + ". A stop exit includes the trailing stop.",
        "",
        "## Costs",
        "",
        *HEADER,
    ]
    for level, result in results.items():
        assert result.metrics is not None
        lines.append(_row(f"{level}x costs", result.metrics))
    lines += ["", "## Walk-Forward Test Folds", "", *HEADER]
    tested: list[BacktestTrade] = []
    folds = walk_forward(START, END)
    for fold in folds:
        inside = entered_between(base.trades, fold.test_start, fold.test_end)
        tested += inside
        label = f"Fold {fold.number}: {fold.test_start:%Y-%m-%d} to {fold.test_end:%Y-%m-%d}"
        lines.append(_row(label, metrics_for(inside, _days(fold.test_start, fold.test_end))))
    if folds:
        span = _days(folds[0].test_start, folds[-1].test_end)
        lines.append(_row("**All test folds**", metrics_for(tested, span)))
    lines += ["", "## By Year and Direction", "", *HEADER]
    for name, members in group(base.trades, _year).items():
        lines.append(_row(name, metrics_for(members, 365)))
    for name, members in group(base.trades, lambda t: t.order.side.value).items():
        lines.append(_row(name, metrics_for(members, _days(START, END))))
    expectancies = sorted(m.expectancy_r for m in random if m.expectancy_r is not None)
    lines += ["", "## Benchmarks", ""]
    if hold is not None:
        lines.append(f"- Buy and hold, no costs: {hold:+.1%}.")
    if expectancies:
        lines.append(
            f"- Random days and directions with the same stops and exit, {len(SEEDS)} seeds: "
            f"mean {statistics.fmean(expectancies):.3f}R, 5th to 95th percentile "
            f"{expectancies[int(len(expectancies) * 0.05)]:.3f}R to "
            f"{expectancies[int(len(expectancies) * 0.95) - 1]:.3f}R. Strategy: "
            f"{_value(base.metrics.expectancy_r)}R."
        )
    lines += [
        "",
        "## Limits",
        "",
        "- One trial, nothing tuned. The holdout was not used (docs/29).",
        "- Fills use 15M candles. Costs are conservative assumptions and funding is real.",
        "- Few, fat-tailed trades: intervals are wide.",
        "- BTC and ETH were chosen with hindsight.",
        "",
    ]
    return "\n".join(lines)


async def backtest(symbol: str) -> str:
    refuse_holdout(START, END)
    inputs = await load(symbol)
    tick = inputs.rules.tick_size
    strategy = DailyTrendStrategy(inputs.days, tick, PARAMETERS)
    results = {level: run(inputs, strategy, level) for level in ("1", "2")}
    random = []
    for seed in SEEDS:
        entries = RandomDailyEntries(
            inputs.days, tick, PARAMETERS, results["1"].signals, seed, (START, END)
        )
        metrics = run(inputs, entries).metrics
        assert metrics is not None
        random.append(metrics)
    return render(inputs, results, random)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT"])
    arguments = parser.parse_args()
    for symbol in arguments.symbols:
        text = asyncio.run(backtest(symbol))
        name = symbol.removesuffix("USDT").lower()
        (REPORT_DIR / f"trend-backtest-{name}.md").write_text(text)
        print(text)


if __name__ == "__main__":
    main()
