"""Run the 4H gap and 15M CHoCH study once (docs/35): six coins, before the frozen holdout.

The rules and the decision rule were pre-registered. The result decides whether the strategy
joins the money plan (D045), and at what share.
"""

import asyncio
import statistics
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

from trading_intel.backtesting.analysis import entered_between, exit_templates, group, metrics_for
from trading_intel.backtesting.benchmarks import RandomTrendEntries
from trading_intel.backtesting.engine import (
    BacktestEngine,
    BacktestResult,
    BacktestTrade,
    CostModel,
)
from trading_intel.backtesting.engine import Strategy as EngineStrategy
from trading_intel.backtesting.metrics import Metrics
from trading_intel.backtesting.report import STATEMENT
from trading_intel.backtesting.windows import refuse_holdout, walk_forward
from trading_intel.domain.signals import Action
from trading_intel.entrypoints.coin_replication import COINS, NEW_COINS
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
)
from trading_intel.risk_management.allocation import Evidence, evidence_share, loses_on_coin
from trading_intel.trade_signals.fvg_choch_strategy import (
    STRATEGY_NAME,
    STRATEGY_VERSION,
    FvgChochParameters,
    FvgChochStrategy,
)

PARAMETERS: Final = FvgChochParameters()
REPORT: Final = REPORT_DIR / "fvg-choch.md"


@dataclass
class CoinRun:
    symbol: str
    results: dict[str, BacktestResult]
    funnel: Counter[str]
    proposed: int
    benchmark: list[list[BacktestTrade]] = field(default_factory=list)  # One list per seed.


def run(inputs: Inputs, strategy: EngineStrategy, stress: str = "1") -> BacktestResult:
    """15M decisions filled on the same 15M candles. The engine decides on `setup` closes."""
    return BacktestEngine(
        inputs.instrument,
        inputs.rules,
        inputs.fills,
        inputs.fills,
        inputs.four_hours,
        inputs.days,
        inputs.funding,
        costs=CostModel().stressed(stress),
        strategy=strategy,
        skip_signals_in_trade=True,
    ).run(START, END)


def funnel(strategy: FvgChochStrategy) -> Counter[str]:
    """What the strategy decided at every 15M CHoCH in the window."""
    counts: Counter[str] = Counter()
    for index in sorted(strategy.changes):
        moment = strategy.series.close_time[index]
        if START <= moment < END:
            decision = strategy.decide(moment)
            proposed = decision.action in (Action.BUY, Action.SELL)
            counts["proposed" if proposed else decision.reasons[0].split(":")[0]] += 1
    return counts


def run_coin(inputs: Inputs) -> CoinRun:
    strategy = FvgChochStrategy(inputs.fills, inputs.four_hours, inputs.rules.tick_size, PARAMETERS)
    results = {level: run(inputs, strategy, level) for level in STRESS}
    counts = funnel(strategy)
    coin = CoinRun(inputs.symbol, results, counts, counts["proposed"])
    templates = exit_templates(results["1"].trades)
    if templates:
        for seed in SEEDS:
            entries = RandomTrendEntries(strategy, templates, coin.proposed, seed, START, END)
            coin.benchmark.append(run(inputs, entries).trades)
    return coin


def _days() -> int:
    return max((END - START).days, 1)


def _trades(runs: Sequence[CoinRun], level: str = "1") -> list[BacktestTrade]:
    return [trade for coin in runs for trade in coin.results[level].trades]


def _value(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:+.{digits}f}"


def _band(metrics: Metrics) -> str:
    interval = metrics.expectancy_interval
    return f"{interval[0]:+.2f} to {interval[1]:+.2f}" if interval else "n/a"


def _row(label: str, metrics: Metrics) -> str:
    rate = "n/a" if metrics.win_rate is None else f"{metrics.win_rate:.2f}"
    factor = "n/a" if metrics.profit_factor is None else f"{metrics.profit_factor:.2f}"
    return (
        f"| {label} | {metrics.trades} | {rate} | {_value(metrics.expectancy_r)} | "
        f"{_band(metrics)} | {factor} | {metrics.net_pnl:.0f} |"
    )


def pooled_benchmark(runs: Sequence[CoinRun]) -> Benchmark | None:
    """Each seed's random trades pooled across the coins, as one expectancy per seed."""
    if not runs or any(len(coin.benchmark) != len(SEEDS) for coin in runs):
        return None
    expectancies: list[float] = []
    counts: list[int] = []
    for position in range(len(SEEDS)):
        trades = [trade for coin in runs for trade in coin.benchmark[position]]
        metrics = metrics_for(trades, _days())
        counts.append(metrics.trades)
        if metrics.expectancy_r is not None:
            expectancies.append(metrics.expectancy_r)
    return Benchmark(expectancies, counts)


def evidence_of(runs: Sequence[CoinRun]) -> Evidence:
    new = [coin for coin in runs if coin.symbol in NEW_COINS]
    pooled = metrics_for(_trades(runs), _days())
    return Evidence(
        pooled_mean=pooled.expectancy_r or 0.0,
        pooled_interval=pooled.expectancy_interval,
        new_coins_mean=metrics_for(_trades(new), _days()).expectancy_r,
        doubled_costs_mean=metrics_for(_trades(runs, "2"), _days()).expectancy_r,
    )


def decision_lines(runs: Sequence[CoinRun]) -> list[str]:
    """The rule pre-registered in docs/35."""
    evidence = evidence_of(runs)
    if evidence.pooled_mean <= 0:
        return [
            f"Pooled six-coin expectancy {_value(evidence.pooled_mean)}R is at zero or below. "
            "**Rejected**: the strategy stays out of live trading, the paper loop and Claude's "
            "evidence."
        ]
    share = evidence_share(evidence)
    left_out = [
        coin.symbol
        for coin in runs
        if loses_on_coin(metrics_for(coin.results["1"].trades, _days()).expectancy_interval)
    ]
    return [
        f"Pooled six-coin expectancy {_value(evidence.pooled_mean)}R is above zero. It joins "
        f"the money plan at a share of **{share}** of the 1% risk (docs/33 rule: interval "
        f"{_band(metrics_for(_trades(runs), _days()))}, four coins pooled "
        f"{_value(evidence.new_coins_mean)}R, 2x costs {_value(evidence.doubled_costs_mean)}R).",
        "",
        f"Coins left out, lost with 95% confidence: {', '.join(left_out) or 'none'}.",
    ]


def render(runs: Sequence[CoinRun]) -> str:
    base = _trades(runs)
    days = _days()
    lines = [
        "# 4H Gap and 15M CHoCH Study",
        "",
        STATEMENT,
        "",
        f"Strategy `{STRATEGY_NAME}` version {STRATEGY_VERSION}, pre-registered in "
        "[35-FVG-CHOCH-STRATEGY.md](../35-FVG-CHOCH-STRATEGY.md) and run once. Period "
        f"{START:%Y-%m-%d}, or the coin's first candle, to {END:%Y-%m-%d}, before the frozen "
        "holdout. Each coin is a separate 10,000 account at 1% risk per trade. Fills use 15M "
        "candles.",
        "",
        "## By Coin, Normal Costs",
        "",
        "| Coin | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | "
        "Max drawdown | Expectancy at 2x costs |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for coin in runs:
        metrics = metrics_for(coin.results["1"].trades, days)
        doubled = metrics_for(coin.results["2"].trades, days)
        rate = "n/a" if metrics.win_rate is None else f"{metrics.win_rate:.2f}"
        factor = "n/a" if metrics.profit_factor is None else f"{metrics.profit_factor:.2f}"
        lines.append(
            f"| {coin.symbol} | {metrics.trades} | {rate} | {_value(metrics.expectancy_r)} | "
            f"{_band(metrics)} | {factor} | {metrics.max_drawdown:.1%} | "
            f"{_value(doubled.expectancy_r)} |"
        )
    lines += ["", "## Pooled", "", *HEADER]
    new = [coin for coin in runs if coin.symbol in NEW_COINS]
    for level in STRESS:
        lines.append(_row(f"Six coins at {level}x costs", metrics_for(_trades(runs, level), days)))
    lines.append(_row("SOL, XRP, BNB and DOGE at 1x costs", metrics_for(_trades(new), days)))
    exits = Counter(t.result.exit_reason for t in base)
    signals = sum(coin.results["1"].signals for coin in runs)
    lines += [
        "",
        f"Signals that reached the risk engine: {signals}. Filled trades: {len(base)}. Exits: "
        + ", ".join(f"{reason} {count}" for reason, count in exits.most_common())
        + ".",
        "",
        "## Funnel",
        "",
        "Every 15M CHoCH in the window, on all six coins, and what the strategy decided there.",
        "",
        "| What happened at a CHoCH | Count |",
        "|---|---|",
    ]
    counts: Counter[str] = Counter()
    for coin in runs:
        counts.update(coin.funnel)
    lines += [f"| {reason} | {count} |" for reason, count in counts.most_common()]
    rejections: Counter[str] = Counter()
    for coin in runs:
        rejections.update({code.value: n for code, n in coin.results["1"].rejections.items()})
    if rejections:
        listed = ", ".join(f"{code} {n}" for code, n in rejections.most_common())
        lines += ["", f"Risk engine rejections: {listed}."]
    folds, tested = fold_lines(base)
    stressed: list[BacktestTrade] = []
    for fold in walk_forward(START, END):
        stressed += entered_between(_trades(runs, "1.5"), fold.test_start, fold.test_end)
    lines += ["", "## Walk-Forward Test Folds, Six Coins Pooled", "", *folds, ""]
    lines += ["## By Year and Side, Six Coins Pooled", "", *HEADER]
    for name, members in group(base, lambda t: f"{t.signal_time:%Y}").items():
        lines.append(_row(name, metrics_for(members, 365)))
    for name, members in group(base, lambda t: t.order.side.value).items():
        lines.append(_row(name, metrics_for(members, days)))
    bench = pooled_benchmark(runs)
    lines += ["", "## Benchmark", ""]
    pooled = metrics_for(base, days)
    if bench and bench.expectancies:
        ordered = sorted(bench.expectancies)
        lines.append(
            f"Random 15M closes where the 4H trend is up or down, entering at market in that "
            f"direction with this strategy's stops and targets, {len(SEEDS)} seeds of about "
            f"{statistics.fmean(bench.trades):.0f} trades pooled across the coins: mean "
            f"{statistics.fmean(ordered):+.3f}R, 5th to 95th percentile "
            f"{ordered[int(len(ordered) * 0.05)]:+.3f}R to "
            f"{ordered[int(len(ordered) * 0.95) - 1]:+.3f}R. Strategy: "
            f"{_value(pooled.expectancy_r)}R."
        )
    else:
        lines.append("Not run: a coin had no trades to copy exits from.")
    lines += [
        "",
        "## Promotion Gate from docs/27, Reported Only",
        "",
        *gate_lines(tested, stressed, bench),
        "",
        "## Decision",
        "",
        *decision_lines(runs),
        "",
        "## Limits",
        "",
        "- One trial, nothing tuned. The holdout was not used.",
        "- Fills use 15M candles. A stop and a target in one candle count as the stop, and a "
        "target in the candle where the limit fills is not counted.",
        "- Limit fills pay the maker fee and no spread, while the benchmark's market entries pay "
        "the taker fee, spread and slippage.",
        "- The six coins move together, they are survivors, and several strategies have been "
        "tested on these years.",
        "",
    ]
    return "\n".join(lines)


async def study() -> str:
    refuse_holdout(START, END)
    runs: list[CoinRun] = []
    for symbol in COINS:
        runs.append(run_coin(await load(symbol)))
        print(f"{symbol} done", flush=True)
    return render(runs)


def main() -> None:
    text = asyncio.run(study())
    REPORT.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
