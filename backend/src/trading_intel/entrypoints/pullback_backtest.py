"""Backtest the trend pullback strategy on history from before the frozen holdout (docs/31)."""

import argparse
import asyncio
import statistics
from collections import Counter
from datetime import datetime
from typing import Final

from trading_intel.backtesting.analysis import (
    buy_and_hold,
    entered_between,
    exit_templates,
    group,
    metrics_for,
)
from trading_intel.backtesting.benchmarks import RandomTrendEntries
from trading_intel.backtesting.engine import BacktestResult, BacktestTrade
from trading_intel.backtesting.metrics import Metrics
from trading_intel.backtesting.report import STATEMENT, metrics_table
from trading_intel.backtesting.windows import refuse_holdout, walk_forward
from trading_intel.entrypoints.pattern_backtest import (
    END,
    HEADER,
    REPORT_DIR,
    SEEDS,
    START,
    STRESS,
    Benchmark,
    Inputs,
    fold_lines,
    gate_lines,
    load,
    run,
)
from trading_intel.trade_signals.pattern_strategy import PatternStrategy
from trading_intel.trade_signals.pullback_strategy import (
    STRATEGY_NAME,
    STRATEGY_VERSION,
    PullbackParameters,
    PullbackStrategy,
)

PARAMETERS: Final = PullbackParameters()


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


def _candle(trade: BacktestTrade) -> str:
    decision = trade.decision
    return decision.patterns[0].pattern_type if decision and decision.patterns else "unknown"


def funnel(strategy: PullbackStrategy) -> Counter[str]:
    """Why each 1H close in the window did or did not become a proposal."""
    counts: Counter[str] = Counter()
    for moment in strategy.base.series.close_time:
        if START <= moment < END:
            decision = strategy.decide(moment)
            counts["proposed" if decision.proposal else decision.reasons[0].split(":")[0]] += 1
    return counts


def benchmark(
    inputs: Inputs, strategy: PullbackStrategy, count: int, result: BacktestResult
) -> Benchmark | None:
    """Random with-trend 1H closes, given the stops and targets of the strategy's own trades."""
    templates = exit_templates(result.trades)
    if not templates:
        return None
    expectancies: list[float] = []
    trades: list[int] = []
    for seed in SEEDS:
        entries = RandomTrendEntries(strategy.base, templates, count, seed, START, END)
        metrics = run(inputs, entries).metrics
        assert metrics is not None
        trades.append(metrics.trades)
        if metrics.expectancy_r is not None:
            expectancies.append(metrics.expectancy_r)
    return Benchmark(expectancies, trades)


def render(
    inputs: Inputs,
    results: dict[str, BacktestResult],
    counts: Counter[str],
    bench: Benchmark | None,
) -> str:
    base = results["1"]
    assert base.metrics is not None
    hold = buy_and_hold(inputs.days, START, END)
    exits = Counter(t.result.exit_reason for t in base.trades)
    folds, tested = fold_lines(base.trades)
    stressed: list[BacktestTrade] = []
    for fold in walk_forward(START, END):
        stressed += entered_between(results["1.5"].trades, fold.test_start, fold.test_end)
    lines = [
        f"# Trend Pullback Backtest: {inputs.symbol} Perpetual",
        "",
        STATEMENT,
        "",
        f"Strategy `{STRATEGY_NAME}` version {STRATEGY_VERSION}, registered before any run in "
        f"[31-PULLBACK-STRATEGY.md](../31-PULLBACK-STRATEGY.md). Period {START:%Y-%m-%d} to "
        f"{END:%Y-%m-%d}, before the frozen holdout.",
        "",
        "## Normal Costs",
        "",
        *metrics_table(base.metrics),
        "",
        f"Signals that reached the risk engine: {base.signals}. Exits: "
        + ", ".join(f"{reason} {count}" for reason, count in exits.most_common())
        + ".",
        "",
        "## Funnel",
        "",
        "| What happened at a 1H close | Count |",
        "|---|---|",
        *(f"| {reason} | {count} |" for reason, count in counts.most_common()),
        "",
        "## Costs",
        "",
        *HEADER,
    ]
    for level, result in results.items():
        assert result.metrics is not None
        lines.append(_row(f"{level}x costs", result.metrics))
    lines += ["", "## Walk-Forward Test Folds", "", *folds, "", "## By Year, Side and Candle", ""]
    lines += [*HEADER]
    for name, members in group(base.trades, lambda t: f"{t.signal_time:%Y}").items():
        lines.append(_row(name, metrics_for(members, 365)))
    for name, members in group(base.trades, lambda t: t.order.side.value).items():
        lines.append(_row(name, metrics_for(members, _days(START, END))))
    for name, members in group(base.trades, _candle).items():
        lines.append(_row(name, metrics_for(members, _days(START, END))))
    lines += ["", "## Benchmarks", ""]
    if hold is not None:
        lines.append(f"- Buy and hold, no costs: {hold:+.1%} over the period.")
    if bench and bench.expectancies:
        ordered = sorted(bench.expectancies)
        lines.append(
            f"- Random 1H closes where 4H and 1D agree, with this strategy's stops and targets, "
            f"{len(SEEDS)} seeds of about {statistics.fmean(bench.trades):.0f} trades: mean "
            f"{statistics.fmean(ordered):.3f}R, 5th to 95th percentile "
            f"{ordered[int(len(ordered) * 0.05)]:.3f}R to "
            f"{ordered[int(len(ordered) * 0.95) - 1]:.3f}R. Strategy: "
            f"{_value(base.metrics.expectancy_r)}R."
        )
    lines += [
        "",
        "## Promotion Gate",
        "",
        *gate_lines(tested, stressed, bench),
        "",
        "## Limits",
        "",
        "- One trial, nothing tuned. The holdout was not used (docs/31).",
        "- Fills use 15M candles. Costs are conservative assumptions and funding is real.",
        "- Several strategies have been tested on these years, so a borderline result is weak.",
        "- BTC and ETH were chosen with hindsight.",
        "",
    ]
    return "\n".join(lines)


async def backtest(symbol: str) -> str:
    refuse_holdout(START, END)
    inputs = await load(symbol)
    base = PatternStrategy(inputs.hours, inputs.four_hours, inputs.days, inputs.rules.tick_size)
    strategy = PullbackStrategy(base, PARAMETERS)
    counts = funnel(strategy)
    results = {level: run(inputs, strategy, level) for level in STRESS}
    bench = benchmark(inputs, strategy, counts["proposed"], results["1"])
    return render(inputs, results, counts, bench)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT"])
    arguments = parser.parse_args()
    for symbol in arguments.symbols:
        text = asyncio.run(backtest(symbol))
        name = symbol.removesuffix("USDT").lower()
        (REPORT_DIR / f"pullback-backtest-{name}.md").write_text(text)
        print(text)


if __name__ == "__main__":
    main()
