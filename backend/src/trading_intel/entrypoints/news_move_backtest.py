"""Context for the news move strategy (docs/40): its price rules alone, without the news check.

There is no labelled news history, so the strategy itself cannot be backtested. This measures
what strong 1H moves with a strong close did on the first six coins from 2020 to the holdout,
in the shared simulator, at normal and stressed costs. It does not stop the strategy, which
trades by the owner's choice (D056).
"""

import asyncio
import statistics
from typing import Final

from trading_intel.backtesting.engine import BacktestTrade
from trading_intel.backtesting.metrics import bootstrap_interval
from trading_intel.backtesting.windows import refuse_holdout
from trading_intel.entrypoints import pattern_backtest
from trading_intel.entrypoints.coin_replication import COINS
from trading_intel.entrypoints.pattern_backtest import END, REPORT_DIR, START, load
from trading_intel.trade_signals.news_move_strategy import NewsMoveStrategy

LEVELS: Final = ("1", "2")
REPORT: Final = REPORT_DIR / "news-move-price-only.md"


def _r(trade: BacktestTrade) -> float:
    return float(trade.result.net_pnl / trade.planned_risk)


async def study() -> str:
    refuse_holdout(START, END)
    pooled: dict[str, list[float]] = {level: [] for level in LEVELS}
    lines = [
        "# News Move Strategy: Price Rules Alone",
        "",
        "Context for docs/40, not a test of the strategy: no news check, because there is no",
        f"labelled news history. Window {START:%Y-%m-%d} to {END:%Y-%m-%d}. Simulated results.",
        "",
        "| Coin | Trades | Mean R | Win rate | Mean R at stressed costs |",
        "|---|---|---|---|---|",
    ]
    for symbol in COINS:
        inputs = await load(symbol)
        strategy = NewsMoveStrategy(inputs.hours, inputs.rules.tick_size)
        found = {
            level: [_r(t) for t in pattern_backtest.run(inputs, strategy, level).trades]
            for level in LEVELS
        }
        for level in LEVELS:
            pooled[level] += found[level]
        normal, stressed = found["1"], found["2"]
        mean = statistics.fmean(normal) if normal else float("nan")
        wins = sum(r > 0 for r in normal) / len(normal) if normal else float("nan")
        hard = statistics.fmean(stressed) if stressed else float("nan")
        lines.append(f"| {symbol} | {len(normal)} | {mean:+.3f} | {wins:.0%} | {hard:+.3f} |")
        print(f"{symbol} done", flush=True)
    lines.append("")
    for level, label in (("1", "normal costs"), ("2", "stressed costs")):
        values = pooled[level]
        band = bootstrap_interval(values)
        interval = f"{band[0]:+.3f} to {band[1]:+.3f}" if band else "n/a"
        mean = statistics.fmean(values) if values else float("nan")
        lines.append(
            f"Pooled, {label}: {len(values)} trades, mean {mean:+.3f}R, 95% interval {interval}."
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    text = asyncio.run(study())
    REPORT.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
