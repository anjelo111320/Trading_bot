"""Run the crash warning study once, on history before the frozen holdout (docs/32)."""

import argparse
import asyncio
import random
import statistics
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final

import numpy as np
import numpy.typing as npt

from trading_intel.backtesting.engine import BacktestTrade
from trading_intel.backtesting.report import STATEMENT
from trading_intel.backtesting.windows import refuse_holdout
from trading_intel.domain.signals import Side
from trading_intel.entrypoints import trend_backtest
from trading_intel.entrypoints.pattern_backtest import END, REPORT_DIR, START, load, run
from trading_intel.market_structure.shock import VOLUME_MULTIPLE, down_warnings
from trading_intel.technical_analysis.series import CandleSeries, FloatArray
from trading_intel.technical_analysis.volatility import atr
from trading_intel.trade_signals.pattern_strategy import PatternStrategy
from trading_intel.trade_signals.trend_strategy import DailyTrendStrategy

COINS: Final = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT")
FALL_CANDLES: Final = 6
FALL_ATR: Final = 6.0
FILTER_WINDOW: Final = timedelta(hours=12)
SEEDS: Final = range(1, 21)
SENSITIVITY: Final = (1.5, 3.0)
MIN_LIFT: Final = 2.0
Flags = npt.NDArray[np.bool_]


def large_falls_ahead(series: CandleSeries, unit: FloatArray) -> Flags:
    """True at a close whose next 6 lows reach 6 ATR below it.

    This looks ahead on purpose. It labels outcomes for the study and never feeds a decision.
    """
    flags = np.zeros(len(series), dtype=bool)
    for index in range(len(series) - FALL_CANDLES):
        size = float(unit[index])
        if size == size and size > 0:
            lowest = series.low[index + 1 : index + 1 + FALL_CANDLES].min()
            flags[index] = lowest <= series.close[index] - FALL_ATR * size
    return flags


@dataclass
class Quality:
    closes: int = 0
    falls: int = 0
    warnings: int = 0
    hits: int = 0
    episodes: int = 0
    caught: int = 0
    days: float = 0.0
    leads: list[float] = field(default_factory=list)
    random_hits: list[int] = field(default_factory=lambda: [0 for _ in SEEDS])

    def merge(self, other: Quality) -> None:
        self.closes += other.closes
        self.falls += other.falls
        self.warnings += other.warnings
        self.hits += other.hits
        self.episodes += other.episodes
        self.caught += other.caught
        self.days += other.days
        self.leads += other.leads
        self.random_hits = [a + b for a, b in zip(self.random_hits, other.random_hits, strict=True)]

    @property
    def base_rate(self) -> float:
        return self.falls / self.closes if self.closes else 0.0

    @property
    def precision(self) -> float:
        return self.hits / self.warnings if self.warnings else 0.0

    @property
    def lift(self) -> float:
        return self.precision / self.base_rate if self.base_rate else 0.0

    @property
    def random_p95(self) -> float:
        if not self.warnings:
            return 0.0
        shares = sorted(hits / self.warnings for hits in self.random_hits)
        return shares[int(len(shares) * 0.95) - 1]


def quality(series: CandleSeries, warn: Flags, ahead: Flags, eligible: Flags, coin: int) -> Quality:
    result = Quality()
    rows = np.flatnonzero(eligible)
    if len(rows) == 0:
        return result
    result.closes = len(rows)
    result.falls = int(ahead[rows].sum())
    warned = rows[warn[rows]]
    result.warnings = len(warned)
    result.hits = int(ahead[warned].sum())
    span = series.close_time[rows[-1]] - series.close_time[rows[0]]
    result.days = span.total_seconds() / 86400
    index = 0
    while index < len(series):
        if not (eligible[index] and ahead[index]):
            index += 1
            continue
        start = index
        while index + 1 < len(series) and eligible[index + 1] and ahead[index + 1]:
            index += 1
        result.episodes += 1
        lowest = series.low[start + 1 : index + 1 + FALL_CANDLES].min()
        first = next((i for i in range(start, index + 1) if warn[i]), None)
        if first is not None:
            result.caught += 1
            whole = series.close[start] - lowest
            if whole > 0:
                result.leads.append(float((series.close[first] - lowest) / whole))
        index += 1
    for slot, seed in enumerate(SEEDS):
        rng = random.Random(seed * 100 + coin)  # noqa: S311 - a seeded benchmark, not security.
        sample = rng.sample(list(rows), min(result.warnings, len(rows)))
        result.random_hits[slot] = int(ahead[sample].sum()) if sample else 0
    return result


def split_trades(
    trades: Sequence[BacktestTrade], warned_at: Sequence[datetime]
) -> tuple[list[float], list[float]]:
    """R of the long trades a filter would skip, signalled within 12 hours after a warning,
    and of every other trade."""
    times = sorted(warned_at)
    skipped: list[float] = []
    kept: list[float] = []
    for trade in trades:
        r = float(trade.result.net_pnl / trade.planned_risk) if trade.planned_risk else 0.0
        position = bisect_right(times, trade.signal_time) - 1
        recent = position >= 0 and trade.signal_time - times[position] <= FILTER_WINDOW
        (skipped if trade.order.side is Side.LONG and recent else kept).append(r)
    return skipped, kept


@dataclass
class CoinStudy:
    symbol: str
    main: Quality
    sensitivity: dict[float, Quality]
    pattern: tuple[list[float], list[float]]
    trend: tuple[list[float], list[float]]


async def study(symbol: str, coin: int) -> CoinStudy:
    refuse_holdout(START, END)
    inputs = await load(symbol)
    series = CandleSeries.of(inputs.hours)
    unit = atr(series)
    ahead = large_falls_ahead(series, unit)
    times = series.close_time
    eligible = np.array([START <= t < END for t in times], dtype=bool) & np.concatenate(
        [np.ones(len(series) - FALL_CANDLES, dtype=bool), np.zeros(FALL_CANDLES, dtype=bool)]
    )
    eligible &= np.array([float(u) == float(u) and float(u) > 0 for u in unit], dtype=bool)
    warn = down_warnings(series)
    main = quality(series, warn, ahead, eligible, coin)
    sensitivity = {
        multiple: quality(
            series, down_warnings(series, volume_multiple=multiple), ahead, eligible, coin
        )
        for multiple in SENSITIVITY
    }
    warned_at = [times[i] for i in np.flatnonzero(warn & eligible)]
    tick = inputs.rules.tick_size
    pattern = run(inputs, PatternStrategy(inputs.hours, inputs.four_hours, inputs.days, tick))
    trend = trend_backtest.run(inputs, DailyTrendStrategy(inputs.days, tick))
    return CoinStudy(
        symbol,
        main,
        sensitivity,
        split_trades(pattern.trades, warned_at),
        split_trades(trend.trades, warned_at),
    )


def _mean(values: Sequence[float]) -> str:
    return f"{statistics.fmean(values):+.3f}R" if values else "n/a"


def _row(name: str, q: Quality) -> str:
    lead = f"{statistics.median(q.leads):.0%}" if q.leads else "n/a"
    per_month = q.warnings / (q.days / 30.44) if q.days else 0.0
    return (
        f"| {name} | {q.closes} | {q.base_rate:.2%} | {q.warnings} | {per_month:.1f} | "
        f"{q.precision:.1%} | {q.lift:.1f} | {q.random_p95:.1%} | "
        f"{q.caught} of {q.episodes} | {lead} |"
    )


def render(studies: Sequence[CoinStudy]) -> str:
    pooled = Quality()
    by_multiple = {multiple: Quality() for multiple in SENSITIVITY}
    pattern_skipped: list[float] = []
    pattern_kept: list[float] = []
    trend_skipped: list[float] = []
    trend_kept: list[float] = []
    for item in studies:
        pooled.merge(item.main)
        for multiple, q in item.sensitivity.items():
            by_multiple[multiple].merge(q)
        pattern_skipped += item.pattern[0]
        pattern_kept += item.pattern[1]
        trend_skipped += item.trend[0]
        trend_kept += item.trend[1]
    checks = [
        ("Precision above the random 95th percentile", pooled.precision > pooled.random_p95),
        (f"Lift at least {MIN_LIFT:.0f}", pooled.lift >= MIN_LIFT),
        (
            "Skipped pattern longs lost on average",
            bool(pattern_skipped) and statistics.fmean(pattern_skipped) < 0,
        ),
        (
            "Skipped daily trend longs lost on average",
            bool(trend_skipped) and statistics.fmean(trend_skipped) < 0,
        ),
    ]
    adopted = all(passed for _, passed in checks)
    header = [
        "| | 1H closes | Large fall ahead | Warnings | Per month | Precision | Lift | "
        "Random 95th | Episodes caught | Fall still ahead, median |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    lines = [
        "# Crash Warning Study",
        "",
        STATEMENT,
        "",
        "Pre-registered in [32-SHOCK-STUDY.md](../32-SHOCK-STUDY.md), run once, on history "
        f"from {START:%Y-%m-%d} or listing to {END:%Y-%m-%d}, before the frozen holdout. A down "
        f"warning is a 1H close below the 12-candle low, on volume at least {VOLUME_MULTIPLE:g} "
        "times its 24-candle mean, with takers selling at least 55%. A large fall ahead is a "
        f"low at least {FALL_ATR:g} ATR below the close within {FALL_CANDLES} candles.",
        "",
        "## Warning Quality",
        "",
        *header,
        *(_row(item.symbol, item.main) for item in studies),
        _row("**Pooled**", pooled),
        "",
        "## Sensitivity, Not Used for the Decision",
        "",
        *header,
        *(_row(f"Volume {multiple:g}x, pooled", q) for multiple, q in by_multiple.items()),
        "",
        "## Filter Value",
        "",
        "Long trades whose signal came within 12 hours after a down warning are the ones the "
        "filter would skip.",
        "",
        "| Backtest | Skipped longs | Their mean | Other trades | Their mean |",
        "|---|---|---|---|---|",
        f"| Pattern breakout, trial 1 | {len(pattern_skipped)} | {_mean(pattern_skipped)} | "
        f"{len(pattern_kept)} | {_mean(pattern_kept)} |",
        f"| Daily trend | {len(trend_skipped)} | {_mean(trend_skipped)} | {len(trend_kept)} | "
        f"{_mean(trend_kept)} |",
        "",
        "## Decision Rule",
        "",
        "| Condition | Result |",
        "|---|---|",
        *(f"| {name} | {'Met' if passed else '**Not met**'} |" for name, passed in checks),
        "",
        "Decision: "
        + (
            "**adopt** the filter: no new long for 12 hours after a down warning."
            if adopted
            else "**not adopted**. The result is recorded and nothing changes."
        ),
        "",
    ]
    return "\n".join(lines)


async def main_async(symbols: Sequence[str]) -> str:
    studies = [await study(symbol, coin) for coin, symbol in enumerate(symbols)]
    return render(studies)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="+", default=list(COINS))
    arguments = parser.parse_args()
    text = asyncio.run(main_async(arguments.symbols))
    (REPORT_DIR / "shock-study.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
