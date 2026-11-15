"""Run the daily trend study once (docs/41): version 1 at the daily close against version 2 at
each 1H close, on the first six coins, before the holdout. The decision rule was registered
before this code. Writes docs/reports/trend-intraday.md.
"""

import asyncio
import statistics
from typing import Final

from trading_intel.backtesting.engine import BacktestTrade
from trading_intel.backtesting.metrics import bootstrap_interval
from trading_intel.backtesting.windows import refuse_holdout
from trading_intel.entrypoints import pattern_backtest, trend_backtest
from trading_intel.entrypoints.coin_replication import COINS
from trading_intel.entrypoints.pattern_backtest import END, REPORT_DIR, START, load
from trading_intel.trade_signals.trend_strategy import DailyTrendStrategy, IntradayTrendStrategy

LEVELS: Final = ("1", "2")
# Version 2 may trail version 1 by this much per trade and still replace it (docs/41).
TOLERANCE: Final = 0.05
REPORT: Final = REPORT_DIR / "trend-intraday.md"


def _r(trade: BacktestTrade) -> float:
    return float(trade.result.net_pnl / trade.planned_risk)


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else float("nan")


async def study() -> str:
    refuse_holdout(START, END)
    found: dict[tuple[str, str], list[float]] = {}
    rows = []
    for symbol in COINS:
        inputs = await load(symbol)
        tick = inputs.rules.tick_size
        daily = DailyTrendStrategy(inputs.days, tick, trend_backtest.PARAMETERS)
        hourly = IntradayTrendStrategy(inputs.hours, inputs.days, tick, trend_backtest.PARAMETERS)
        per: dict[tuple[str, str], list[float]] = {}
        for level in LEVELS:
            per["1", level] = [_r(t) for t in trend_backtest.run(inputs, daily, level).trades]
            per["2", level] = [_r(t) for t in pattern_backtest.run(inputs, hourly, level).trades]
        for key, values in per.items():
            found.setdefault(key, []).extend(values)
        rows.append(
            f"| {symbol} | {len(per['1', '1'])} | {_mean(per['1', '1']):+.3f} | "
            f"{len(per['2', '1'])} | {_mean(per['2', '1']):+.3f} | {_mean(per['2', '2']):+.3f} |"
        )
        print(f"{symbol} done", flush=True)
    v1, v2 = found["1", "1"], found["2", "1"]
    band = bootstrap_interval(v2)
    first = _mean(v2) >= _mean(v1) - TOLERANCE
    second = band is not None and band[0] > 0
    adopted = first and second
    v1_band = bootstrap_interval(v1)
    lines = [
        "# Daily Trend, Checked All Day: Results",
        "",
        f"Pre-registered in docs/41. Six coins, {START:%Y-%m-%d} to {END:%Y-%m-%d}, before the "
        "holdout, in the shared simulator. Simulated results; R per trade after fees, spread, "
        "slippage and funding.",
        "",
        "| Coin | V1 trades | V1 mean R | V2 trades | V2 mean R | V2 at 2x costs |",
        "|---|---|---|---|---|---|",
        *rows,
        "",
        f"- Version 1, pooled: {len(v1)} trades, {_mean(v1):+.3f}R a trade, 95% interval "
        f"{v1_band[0]:+.3f} to {v1_band[1]:+.3f}."
        if v1_band
        else "- Version 1: no trades.",
        f"- Version 2, pooled: {len(v2)} trades, {_mean(v2):+.3f}R a trade, 95% interval "
        f"{band[0]:+.3f} to {band[1]:+.3f}; at 2x costs {_mean(found['2', '2']):+.3f}R."
        if band
        else "- Version 2: no trades.",
        f"- Rule 1, at least version 1 less {TOLERANCE}R: {'passed' if first else 'failed'}.",
        f"- Rule 2, interval above zero: {'passed' if second else 'failed'}.",
        f"- Decision: {'version 2 replaces version 1' if adopted else 'version 1 stays'}.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    text = asyncio.run(study())
    REPORT.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
