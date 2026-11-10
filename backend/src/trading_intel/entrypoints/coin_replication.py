"""Run the six-coin replication study once (docs/33): both tested strategies on each core coin.

The rules and the decision rule were pre-registered, and the window ends before the frozen
holdout (D029). The result sets each strategy's share of risk in the money plan (D045).
"""

import argparse
import asyncio
from collections.abc import Sequence
from typing import Final

from trading_intel.backtesting.analysis import metrics_for
from trading_intel.backtesting.engine import BacktestTrade
from trading_intel.backtesting.metrics import Metrics
from trading_intel.backtesting.report import STATEMENT
from trading_intel.backtesting.windows import refuse_holdout
from trading_intel.entrypoints import pattern_backtest, trend_backtest
from trading_intel.entrypoints.pattern_backtest import END, REPORT_DIR, START, load
from trading_intel.risk_management.allocation import (
    QUARTER_SHARE,
    Evidence,
    evidence_share,
    loses_on_coin,
)
from trading_intel.trade_signals.pattern_strategy import STRATEGY_NAME as PATTERN_NAME
from trading_intel.trade_signals.pattern_strategy import PatternStrategy
from trading_intel.trade_signals.trend_strategy import STRATEGY_NAME as TREND_NAME
from trading_intel.trade_signals.trend_strategy import DailyTrendStrategy

COINS: Final = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT")
NEW_COINS: Final = ("SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT")
STRATEGIES: Final = (PATTERN_NAME, TREND_NAME)
LEVELS: Final = ("1", "2")
# Results known before registration (docs/33, "Already Seen").
SEEN: Final = {(TREND_NAME, "XRPUSDT")}

Runs = dict[tuple[str, str, str], list[BacktestTrade]]


async def run_coin(symbol: str) -> Runs:
    """Both strategies at both cost levels, with the parameters that trade live."""
    inputs = await load(symbol)
    tick = inputs.rules.tick_size
    pattern = PatternStrategy(inputs.hours, inputs.four_hours, inputs.days, tick)
    trend = DailyTrendStrategy(inputs.days, tick, trend_backtest.PARAMETERS)
    runs: Runs = {}
    for level in LEVELS:
        runs[(PATTERN_NAME, symbol, level)] = pattern_backtest.run(inputs, pattern, level).trades
        runs[(TREND_NAME, symbol, level)] = trend_backtest.run(inputs, trend, level).trades
    return runs


def _days() -> int:
    return max((END - START).days, 1)


def _pooled(runs: Runs, strategy: str, coins: Sequence[str], level: str = "1") -> Metrics:
    trades = [trade for coin in coins for trade in runs[(strategy, coin, level)]]
    return metrics_for(trades, _days())


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


def evidence_of(runs: Runs, strategy: str) -> Evidence:
    pooled = _pooled(runs, strategy, COINS)
    return Evidence(
        pooled_mean=pooled.expectancy_r or 0.0,
        pooled_interval=pooled.expectancy_interval,
        new_coins_mean=_pooled(runs, strategy, NEW_COINS).expectancy_r,
        doubled_costs_mean=_pooled(runs, strategy, COINS, "2").expectancy_r,
    )


def render(runs: Runs) -> str:
    lines = [
        "# Six-Coin Replication Study",
        "",
        STATEMENT,
        "",
        "Pre-registered in [33-COIN-REPLICATION.md](../33-COIN-REPLICATION.md) and run once. "
        f"Period {START:%Y-%m-%d}, or the coin's first candle, to {END:%Y-%m-%d}, before the "
        "frozen holdout. Each coin is a separate 10,000 account at 1% risk per trade.",
        "",
    ]
    decisions: list[str] = []
    for strategy in STRATEGIES:
        lines += [
            f"## {strategy}",
            "",
            "| Coin | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | "
            "Max drawdown | Expectancy at 2x costs | Note |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        left_out: list[str] = []
        for coin in COINS:
            metrics = metrics_for(runs[(strategy, coin, "1")], _days())
            doubled = metrics_for(runs[(strategy, coin, "2")], _days())
            notes = []
            if (strategy, coin) in SEEN:
                notes.append("seen before registration")
            if coin not in NEW_COINS:
                notes.append("known before, docs/27 and docs/29")
            if loses_on_coin(metrics.expectancy_interval):
                notes.append("lost with 95% confidence")
                left_out.append(coin)
            drawdown = f"{metrics.max_drawdown:.1%}"
            lines.append(_row(coin, metrics, doubled, drawdown, ", ".join(notes)))
        for label, coins in (("Four new coins", NEW_COINS), ("All six coins", COINS)):
            pooled = _pooled(runs, strategy, coins)
            doubled = _pooled(runs, strategy, coins, "2")
            lines.append(_row(f"**{label}**", pooled, doubled, "n/a", "pooled"))
        evidence = evidence_of(runs, strategy)
        share = evidence_share(evidence)
        excluded = ", ".join(left_out) if left_out else "none"
        lines.append("")
        decisions.append(
            f"| {strategy} | {share} | {excluded} | "
            f"{_value(evidence.pooled_mean)}, {_band(_pooled(runs, strategy, COINS))} | "
            f"{_value(evidence.new_coins_mean)} | {_value(evidence.doubled_costs_mean)} |"
        )
    lines += [
        "## Decision",
        "",
        "Applied as pre-registered. A share is a fraction of the account's 1% risk per trade.",
        "",
        "| Strategy | Share | Coins left out | Six coins, mean and interval | Four new coins, "
        "mean | Six coins at 2x costs, mean |",
        "|---|---|---|---|---|---|",
        *decisions,
        f"| trend_break_baseline (15M) | {QUARTER_SHARE} | none | "
        "not testable before the holdout | n/a | n/a |",
        "",
        "## Limits",
        "",
        "- The six coins move together, so their trades are not independent and the pooled "
        "interval is narrower than it should be.",
        "- The coins were chosen in 2026 from those still trading, so they are survivors.",
        "- Pooled drawdown is not shown, because each coin ran as its own account.",
        "- A pass is not proof of future profit.",
        "",
    ]
    return "\n".join(lines)


async def study() -> str:
    refuse_holdout(START, END)
    runs: Runs = {}
    for symbol in COINS:
        # One coin at a time, keeping only its trades, so memory stays small.
        runs.update(await run_coin(symbol))
        print(f"{symbol} done", flush=True)
    return render(runs)


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    text = asyncio.run(study())
    (REPORT_DIR / "coin-replication.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
