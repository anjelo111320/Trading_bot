"""Run the signal score study once (docs/34): every tested trade, scored at its signal.

The conditions and the decision rule were pre-registered, and the window ends before the
frozen holdout (D029). A pass halves the money plan's share for weak signals (D045).
"""

import argparse
import asyncio
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from trading_intel.backtesting.analysis import closed_trade
from trading_intel.backtesting.engine import BacktestTrade
from trading_intel.backtesting.metrics import difference_interval
from trading_intel.backtesting.report import STATEMENT
from trading_intel.backtesting.windows import refuse_holdout
from trading_intel.domain.signals import Side
from trading_intel.entrypoints.coin_replication import COINS, LEVELS, NEW_COINS, runs_of
from trading_intel.entrypoints.pattern_backtest import END, REPORT_DIR, START, load
from trading_intel.technical_analysis.series import CandleSeries
from trading_intel.trade_signals.pattern_strategy import STRATEGY_NAME as PATTERN_NAME
from trading_intel.trade_signals.portfolio import share_of
from trading_intel.trade_signals.signal_score import (
    SCORE_VERSION,
    Conditions,
    FundingView,
    LongTermTrend,
    ScoreViews,
    VolumeView,
)
from trading_intel.trade_signals.trend_strategy import STRATEGY_NAME as TREND_NAME

BITCOIN: Final = "BTCUSDT"
STRATEGIES: Final = (TREND_NAME, PATTERN_NAME)
YEARS: Final = range(2020, 2026)
MIN_YEAR_TRADES: Final = 5
YEARS_NEEDED: Final = 4
WEAK_SHARE: Final = 0.5
CONDITIONS: Final = (
    ("long_term_trend", "Coin's long-term trend"),
    ("bitcoin_trend", "Bitcoin's long-term trend"),
    ("volume", "Volume"),
    ("funding", "Funding"),
)


@dataclass(frozen=True)
class Scored:
    strategy: str
    coin: str
    side: Side
    signal_time: datetime
    exit_time: datetime
    r: float
    conditions: Conditions


def scored(
    trades: Sequence[BacktestTrade], strategy: str, coin: str, views: ScoreViews
) -> list[Scored]:
    """Filled trades with their conditions as known at the signal."""
    rows = []
    for trade in trades:
        closed = closed_trade(trade)
        if closed is None:
            continue
        side = trade.order.side
        rows.append(
            Scored(
                strategy,
                coin,
                side,
                trade.signal_time,
                closed.exit_time,
                float(closed.r_multiple),
                views.conditions(trade.signal_time, side),
            )
        )
    return rows


@dataclass(frozen=True)
class Gap:
    strong: list[float]
    weak: list[float]

    @property
    def difference(self) -> float | None:
        if not self.strong or not self.weak:
            return None
        return statistics.fmean(self.strong) - statistics.fmean(self.weak)

    @property
    def interval(self) -> tuple[float, float] | None:
        return difference_interval(self.strong, self.weak)

    @property
    def above_zero(self) -> bool:
        return self.difference is not None and self.difference > 0


def gap_of(rows: Sequence[Scored]) -> Gap:
    """Scored signals only: a signal with an unknown condition is in neither group."""
    return Gap(
        [row.r for row in rows if row.conditions.weak is False],
        [row.r for row in rows if row.conditions.weak is True],
    )


def years_above(rows: Sequence[Scored]) -> int:
    count = 0
    for year in YEARS:
        gap = gap_of([row for row in rows if row.signal_time.year == year])
        if min(len(gap.strong), len(gap.weak)) >= MIN_YEAR_TRADES and gap.above_zero:
            count += 1
    return count


@dataclass(frozen=True)
class Sizing:
    total: float
    drawdown: float

    @property
    def ratio(self) -> float | None:
        return self.total / self.drawdown if self.drawdown > 0 else None


def sizing(rows: Sequence[Scored], *, with_score: bool) -> Sizing:
    """Cumulative R in exit order, each trade weighed by its strategy's money-plan share."""
    ordered = sorted(rows, key=lambda r: (r.exit_time, r.coin, r.strategy, r.signal_time))
    total = peak = worst = 0.0
    for row in ordered:
        weight = float(share_of(row.strategy))
        if with_score and row.conditions.weak:
            weight *= WEAK_SHARE
        total += weight * row.r
        peak = max(peak, total)
        worst = max(worst, peak - total)
    return Sizing(total, worst)


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


def _number(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.3f}"


def _band(interval: tuple[float, float] | None) -> str:
    return "n/a" if interval is None else f"{interval[0]:+.2f} to {interval[1]:+.2f}"


def checks(rows: Sequence[Scored]) -> list[Check]:
    """The six pre-registered checks, on scored signals at normal costs."""
    known = [row for row in rows if row.conditions.known]
    pooled = gap_of(known)
    interval = pooled.interval
    by_strategy = {name: gap_of([r for r in known if r.strategy == name]) for name in STRATEGIES}
    new = gap_of([r for r in known if r.coin in NEW_COINS])
    by_side = {side: gap_of([r for r in known if r.side is side]) for side in Side}
    years = years_above(known)
    flat, plan = sizing(known, with_score=False), sizing(known, with_score=True)
    return [
        Check(
            "1. Strong minus weak, pooled, with its 95% interval above zero",
            interval is not None and interval[0] > 0,
            f"{_number(pooled.difference)}R, {_band(interval)}",
        ),
        Check(
            "2. Above zero for each strategy",
            all(gap.above_zero for gap in by_strategy.values()),
            ", ".join(f"{name} {_number(gap.difference)}R" for name, gap in by_strategy.items()),
        ),
        Check(
            "3. Above zero on the four new coins pooled",
            new.above_zero,
            f"{_number(new.difference)}R",
        ),
        Check(
            "4. Above zero among longs and among shorts",
            all(gap.above_zero for gap in by_side.values()),
            ", ".join(f"{side.value} {_number(gap.difference)}R" for side, gap in by_side.items()),
        ),
        Check(
            f"5. Above zero in at least {YEARS_NEEDED} of the 6 years",
            years >= YEARS_NEEDED,
            f"{years} of 6",
        ),
        Check(
            "6. Scored sizing has a higher return to drawdown",
            flat.ratio is not None and plan.ratio is not None and plan.ratio > flat.ratio,
            f"{_number(plan.ratio)} against {_number(flat.ratio)} unscored",
        ),
    ]


def _gap_row(label: str, gap: Gap) -> str:
    def mean(values: list[float]) -> str:
        return _number(statistics.fmean(values)) if values else "n/a"

    return (
        f"| {label} | {len(gap.strong)} | {mean(gap.strong)} | {len(gap.weak)} | "
        f"{mean(gap.weak)} | {_number(gap.difference)} | {_band(gap.interval)} |"
    )


GAP_HEADER: Final = [
    "| | Strong trades | Strong mean (R) | Weak trades | Weak mean (R) | Difference (R) | "
    "95% interval |",
    "|---|---|---|---|---|---|---|",
]


def _breakdown(known: Sequence[Scored]) -> list[str]:
    lines = [*GAP_HEADER, _gap_row("**All**", gap_of(known))]
    for name in STRATEGIES:
        lines.append(_gap_row(name, gap_of([r for r in known if r.strategy == name])))
    for coin in COINS:
        lines.append(_gap_row(coin, gap_of([r for r in known if r.coin == coin])))
    lines.append(_gap_row("Four new coins", gap_of([r for r in known if r.coin in NEW_COINS])))
    for side in Side:
        lines.append(_gap_row(side.value, gap_of([r for r in known if r.side is side])))
    for year in YEARS:
        lines.append(_gap_row(str(year), gap_of([r for r in known if r.signal_time.year == year])))
    return lines


def _condition_lines(known: Sequence[Scored]) -> list[str]:
    lines = [
        "| Condition | Strategy | For: trades | For: mean (R) | Against: trades | "
        "Against: mean (R) |",
        "|---|---|---|---|---|---|",
    ]
    for field, label in CONDITIONS:
        for name in STRATEGIES:
            members = [r for r in known if r.strategy == name]
            held = [r.r for r in members if getattr(r.conditions, field) is True]
            failed = [r.r for r in members if getattr(r.conditions, field) is False]
            lines.append(
                f"| {label} | {name} | {len(held)} | "
                f"{_number(statistics.fmean(held)) if held else 'n/a'} | {len(failed)} | "
                f"{_number(statistics.fmean(failed)) if failed else 'n/a'} |"
            )
    return lines


def render(rows: dict[str, list[Scored]]) -> str:
    base = rows["1"]
    known = [row for row in base if row.conditions.known]
    found = checks(base)
    passed = all(check.passed for check in found)
    flat, plan = sizing(known, with_score=False), sizing(known, with_score=True)
    doubled = gap_of([row for row in rows["2"] if row.conditions.known])
    lines = [
        "# Signal Score Study",
        "",
        STATEMENT,
        "",
        f"Score version {SCORE_VERSION}, pre-registered in "
        "[34-SIGNAL-SCORE.md](../34-SIGNAL-SCORE.md) and run once. Period "
        f"{START:%Y-%m-%d}, or the coin's first candle, to {END:%Y-%m-%d}, before the frozen "
        "holdout. Each coin is a separate 10,000 account at 1% risk per trade, with funding "
        "charged in every year.",
        "",
        f"Filled trades: {len(base)}. Scored: {len(known)}. Left out with an unknown condition: "
        f"{len(base) - len(known)}.",
        "",
        "## Decision",
        "",
        "| Check | Result | Passed |",
        "|---|---|---|",
        *(f"| {c.name} | {c.detail} | {'yes' if c.passed else 'no'} |" for c in found),
        "",
        "**The score passes: weak signals get half their strategy's share in the money plan.**"
        if passed
        else "**The score does not pass. Nothing changes in trading.**",
        "",
        "## Strong and Weak Signals at Normal Costs",
        "",
        "A signal is weak when two or more of its conditions are against it.",
        "",
        *_breakdown(known),
        "",
        f"At 2x costs, reported only: difference {_number(doubled.difference)}R, "
        f"{_band(doubled.interval)}.",
        "",
        "## Sizing",
        "",
        "Cumulative R in exit order, pooled over both strategies and six coins, each trade "
        "weighed by its strategy's money-plan share.",
        "",
        "| | Total (R) | Largest fall (R) | Total over largest fall |",
        "|---|---|---|---|",
        f"| Without the score | {flat.total:+.1f} | {flat.drawdown:.1f} | {_number(flat.ratio)} |",
        f"| Weak signals at half | {plan.total:+.1f} | {plan.drawdown:.1f} | "
        f"{_number(plan.ratio)} |",
        "",
        "## Each Condition on Its Own",
        "",
        "A description only. Slicing six ways invites fitting, so none of these can change "
        "trading.",
        "",
        *_condition_lines(known),
        "",
        "## Limits",
        "",
        "- The six coins move together, so their trades are not independent and the intervals "
        "are narrower than they should be.",
        "- A coin's trend and Bitcoin's often agree, so the conditions overlap.",
        "- Early trades with an unknown condition are left out, so 2020 counts less than in "
        "docs/27 and docs/29.",
        "- Funding before March 2023 is charged at the last 15M close, not the mark price.",
        "- A pass is not proof of future profit.",
        "",
    ]
    return "\n".join(lines)


async def study() -> str:
    refuse_holdout(START, END)
    rows: dict[str, list[Scored]] = {level: [] for level in LEVELS}
    bitcoin: LongTermTrend | None = None
    for symbol in COINS:
        # One coin at a time, keeping only its scored trades, so memory stays small.
        inputs = await load(symbol)
        days = CandleSeries.of(inputs.days)
        trend = LongTermTrend(days)
        if symbol == BITCOIN:
            bitcoin = trend
        assert bitcoin is not None, "Bitcoin runs first, so the others can read its trend"
        market = None if symbol == BITCOIN else bitcoin
        funding = FundingView([(event.at, event.rate) for event in inputs.funding])
        views = {
            PATTERN_NAME: ScoreViews(
                trend, market, VolumeView(CandleSeries.of(inputs.hours)), funding
            ),
            TREND_NAME: ScoreViews(trend, market, VolumeView(days), funding),
        }
        for (strategy, coin, level), trades in runs_of(inputs).items():
            rows[level] += scored(trades, strategy, coin, views[strategy])
        print(f"{symbol} done", flush=True)
    return render(rows)


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    text = asyncio.run(study())
    (REPORT_DIR / "signal-score.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
