"""Run the exit rules study once (docs/37): three exit rules on three strategies' own entries.

The rules and the decision rule were pre-registered. Each filled trade is replayed through the
shared simulator with each rule added, so every comparison is on the same entry.
"""

import asyncio
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final

from trading_intel.backtesting.engine import BacktestResult
from trading_intel.backtesting.engine import Strategy as EngineStrategy
from trading_intel.backtesting.exits import (
    Breakeven,
    CheckCounts,
    ExitRule,
    StallExit,
    SwingTrail,
    TradeChecks,
    prior_median_ranges,
    replay,
)
from trading_intel.backtesting.metrics import bootstrap_interval
from trading_intel.backtesting.report import STATEMENT
from trading_intel.backtesting.windows import refuse_holdout
from trading_intel.domain.candles import ClosedCandle
from trading_intel.entrypoints import fvg_choch_backtest, pattern_backtest, trend_backtest
from trading_intel.entrypoints.coin_replication import COINS, NEW_COINS
from trading_intel.entrypoints.pattern_backtest import END, REPORT_DIR, START, Inputs, load
from trading_intel.market_structure.swings import find_swings
from trading_intel.paper_trading.simulator import TradeResult
from trading_intel.technical_analysis.series import CandleSeries
from trading_intel.trade_signals.fvg_choch_strategy import STRATEGY_NAME as FVG_NAME
from trading_intel.trade_signals.fvg_choch_strategy import FvgChochStrategy
from trading_intel.trade_signals.pattern_strategy import STRATEGY_NAME as PATTERN_NAME
from trading_intel.trade_signals.pattern_strategy import PatternStrategy
from trading_intel.trade_signals.trend_strategy import STRATEGY_NAME as TREND_NAME
from trading_intel.trade_signals.trend_strategy import DailyTrendStrategy

STRATEGIES: Final = (TREND_NAME, PATTERN_NAME, FVG_NAME)
RULES: Final = ("breakeven", "stall_exit", "swing_trail")
LEVELS: Final = ("1", "2")
# 95% shared across the strategy and rule pairs (Bonferroni), as pre-registered.
STRICT: Final = 1 - 0.05 / (len(STRATEGIES) * len(RULES))
# Trades open across the live paper and demo accounts on 2026-11-11, for the call estimate.
OPEN_TRADES: Final = 10
CANDLES_PER_DAY: Final = 96
REPORT: Final = REPORT_DIR / "exit-rules.md"

Run = Callable[[Inputs, EngineStrategy, str], BacktestResult]


@dataclass(frozen=True)
class Paired:
    """One filled trade's R with its own exits and with each rule, on the same entry."""

    strategy: str
    coin: str
    level: str
    own: float
    with_rule: dict[str, float]
    acted: dict[str, bool]

    def change(self, rule: str) -> float:
        return self.with_rule[rule] - self.own


@dataclass
class Study:
    pairs: list[Paired] = field(default_factory=list)
    replayed: int = 0
    mismatched: int = 0
    checks: dict[str, CheckCounts] = field(default_factory=dict)


def _r(result: TradeResult, planned: Decimal) -> float:
    return float(result.net_pnl / planned)


def _setups(inputs: Inputs) -> dict[str, tuple[EngineStrategy, list[ClosedCandle], Run]]:
    """Each strategy with the parameters that trade live, its setup candles and its runner."""
    tick = inputs.rules.tick_size
    trend = DailyTrendStrategy(inputs.days, tick, trend_backtest.PARAMETERS)
    pattern = PatternStrategy(inputs.hours, inputs.four_hours, inputs.days, tick)
    gap = FvgChochStrategy(inputs.fills, inputs.four_hours, tick, fvg_choch_backtest.PARAMETERS)
    return {
        TREND_NAME: (trend, inputs.days, trend_backtest.run),
        PATTERN_NAME: (pattern, inputs.hours, pattern_backtest.run),
        FVG_NAME: (gap, inputs.fills, fvg_choch_backtest.run),
    }


def study_coin(inputs: Inputs, study: Study) -> None:
    tick = inputs.rules.tick_size
    open_times = [candle.open_time for candle in inputs.fills]
    medians = prior_median_ranges(inputs.fills)
    for name, (strategy, candles, run) in _setups(inputs).items():
        closes = {candle.close_time: candle.close for candle in candles}
        swings = find_swings(CandleSeries.of(candles))
        rules: list[ExitRule] = [Breakeven(), StallExit(), SwingTrail(swings, tick)]
        trail = getattr(strategy, "trailing_stop", None)
        counts = study.checks.setdefault(name, CheckCounts())
        for level in LEVELS:
            for trade in run(inputs, strategy, level).trades:
                checks = TradeChecks(counts, medians) if level == "1" else None
                own = replay(
                    trade.order, trade.signal_time, inputs.fills, open_times, closes,
                    inputs.funding, END, trail=trail, checks=checks,
                )  # fmt: skip
                study.replayed += 1
                study.mismatched += own.result != trade.result
                with_rule: dict[str, float] = {}
                acted: dict[str, bool] = {}
                for rule in rules:
                    again = replay(
                        trade.order, trade.signal_time, inputs.fills, open_times, closes,
                        inputs.funding, END, trail=trail, rule=rule,
                    )  # fmt: skip
                    with_rule[rule.name] = _r(again.result, trade.planned_risk)
                    acted[rule.name] = again.acted
                own_r = _r(trade.result, trade.planned_risk)
                study.pairs.append(Paired(name, inputs.symbol, level, own_r, with_rule, acted))


def _pairs(
    study: Study, strategy: str, level: str = "1", coins: Sequence[str] = COINS
) -> list[Paired]:
    return [
        p for p in study.pairs if p.strategy == strategy and p.level == level and p.coin in coins
    ]


def _mean(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _value(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:+.{digits}f}"


def _band(interval: tuple[float, float] | None) -> str:
    return f"{interval[0]:+.3f} to {interval[1]:+.3f}" if interval else "n/a"


@dataclass(frozen=True)
class Verdict:
    trades: int
    acted: int
    own: float | None
    with_rule: float | None
    change: float | None
    interval: tuple[float, float] | None
    strict: tuple[float, float] | None
    doubled: float | None
    four_coins: float | None

    @property
    def passes(self) -> bool:
        return (
            self.change is not None
            and self.change > 0
            and self.strict is not None
            and self.strict[0] > 0
            and self.doubled is not None
            and self.doubled > 0
            and self.four_coins is not None
            and self.four_coins > 0
        )


def verdict(study: Study, strategy: str, rule: str) -> Verdict:
    pairs = _pairs(study, strategy)
    changes = [p.change(rule) for p in pairs]
    return Verdict(
        trades=len(pairs),
        acted=sum(p.acted[rule] for p in pairs),
        own=_mean([p.own for p in pairs]),
        with_rule=_mean([p.with_rule[rule] for p in pairs]),
        change=_mean(changes),
        interval=bootstrap_interval(changes),
        strict=bootstrap_interval(changes, STRICT),
        doubled=_mean([p.change(rule) for p in _pairs(study, strategy, "2")]),
        four_coins=_mean([p.change(rule) for p in _pairs(study, strategy, coins=NEW_COINS)]),
    )


def decision_lines(study: Study) -> list[str]:
    if study.mismatched:
        return [
            f"**Void.** {study.mismatched} replays with no rule did not match the engine, so no "
            "rule is adopted until the replay is fixed and the study is run again."
        ]
    lines = ["Applied as pre-registered.", ""]
    for strategy in STRATEGIES:
        passed = [(rule, verdict(study, strategy, rule)) for rule in RULES]
        passing = [(rule, v) for rule, v in passed if v.passes]
        if passing:
            rule, chosen = max(passing, key=lambda item: item[1].change or 0.0)
            lines.append(
                f"- `{strategy}`: **`{rule}` is adopted**, mean change "
                f"{_value(chosen.change)}R a trade, in the `Portfolio` account and on Binance "
                "demo. `Paper` and `Demo` keep the strategy's own exits."
            )
        else:
            lines.append(f"- `{strategy}`: no rule passed. It **keeps its own exits**.")
    return lines


def render(study: Study) -> str:
    lines = [
        "# Exit Rules Study",
        "",
        STATEMENT,
        "",
        "Pre-registered in [37-EXIT-RULES.md](../37-EXIT-RULES.md) and run once. Period "
        f"{START:%Y-%m-%d}, or the coin's first candle, to {END:%Y-%m-%d}, before the frozen "
        "holdout. Each coin is a separate 10,000 account at 1% risk per trade. Fills use 15M "
        "candles. Every change is in R per trade, a rule's result minus the strategy's own "
        "exits on the same entry.",
        "",
        f"Replay check: {study.replayed} trades replayed with no rule, {study.mismatched} "
        "different from the backtest engine.",
        "",
    ]
    for strategy in STRATEGIES:
        lines += [
            f"## {strategy}",
            "",
            "| Rule | Trades | Rule acted on | Own exits (R) | With the rule (R) | Change | "
            "95% interval | 99.4% interval | Change at 2x costs | Change, four coins | Passes |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for rule in RULES:
            v = verdict(study, strategy, rule)
            lines.append(
                f"| {rule} | {v.trades} | {v.acted} | {_value(v.own)} | {_value(v.with_rule)} | "
                f"{_value(v.change)} | {_band(v.interval)} | {_band(v.strict)} | "
                f"{_value(v.doubled)} | {_value(v.four_coins)} | {'yes' if v.passes else 'no'} |"
            )
        lines += [
            "",
            "Where each rule acted, at 1x costs, split by how the trade did with its own exits:",
            "",
            "| Rule | Acted on | Own winners: trades, mean change | Own losers: trades, mean "
            "change |",
            "|---|---|---|---|",
        ]
        pairs = _pairs(study, strategy)
        for rule in RULES:
            acted = [p for p in pairs if p.acted[rule]]
            won = [p.change(rule) for p in acted if p.own > 0]
            lost = [p.change(rule) for p in acted if p.own <= 0]
            lines.append(
                f"| {rule} | {len(acted)} | {len(won)}, {_value(_mean(won))} | "
                f"{len(lost)}, {_value(_mean(lost))} |"
            )
        lines += [
            "",
            "Mean change by coin, at 1x costs:",
            "",
            "| Rule | " + " | ".join(COINS) + " |",
            "|---|" + "---|" * len(COINS),
        ]
        for rule in RULES:
            cells = [
                _value(_mean([p.change(rule) for p in _pairs(study, strategy, coins=(coin,))]))
                for coin in COINS
            ]
            lines.append(f"| {rule} | " + " | ".join(cells) + " |")
        lines.append("")
    lines += [
        "## AI Check Counts",
        "",
        "How often an AI exit manager would have been asked, from the trades with their own "
        "exits at 1x costs, at each 15M close while a trade was open. CHoCH against the trade, "
        "news and events are not counted, so these are lower bounds.",
        "",
        "| Strategy | Trades | Open trade-days | Stall past +1R | Rejected near a target | "
        "Volatility jump | Checks per trade | Checks per open trade-day |",
        "|---|---|---|---|---|---|---|---|",
    ]
    total = CheckCounts()
    for strategy in STRATEGIES:
        counts = study.checks.get(strategy, CheckCounts())
        total.trades += counts.trades
        total.open_candles += counts.open_candles
        total.checks.update(counts.checks)
        lines.append(_check_row(strategy, counts))
    lines.append(_check_row("**All three**", total))
    days = total.open_candles / CANDLES_PER_DAY
    per_day = total.total / days if days else 0.0
    lines += [
        "",
        f"At about {OPEN_TRADES} open trades, that is about {per_day * OPEN_TRADES:.0f} checks "
        "a day, before CHoCH, news and event checks.",
        "",
        "## Decision",
        "",
        *decision_lines(study),
        "",
        "## Limits",
        "",
        "- One trial, nothing tuned. The holdout was not used.",
        "- Entries are held fixed, so a coin freed earlier for its next signal is not counted.",
        "- Fills use 15M candles, and a market exit at the next open uses the backtest costs.",
        "- The six coins move together, they are survivors, and several strategies have been "
        "tested on these years.",
        "",
    ]
    return "\n".join(lines)


def _check_row(label: str, counts: CheckCounts) -> str:
    days = counts.open_candles / CANDLES_PER_DAY
    per_trade = counts.total / counts.trades if counts.trades else 0.0
    per_day = counts.total / days if days else 0.0
    return (
        f"| {label} | {counts.trades} | {days:.0f} | {counts.checks['stall past +1R']} | "
        f"{counts.checks['rejected near a target']} | {counts.checks['volatility jump']} | "
        f"{per_trade:.2f} | {per_day:.2f} |"
    )


async def study() -> str:
    refuse_holdout(START, END)
    result = Study()
    for symbol in COINS:
        # One coin at a time, keeping only the paired results, so memory stays small.
        study_coin(await load(symbol), result)
        print(f"{symbol} done", flush=True)
    return render(result)


def main() -> None:
    text = asyncio.run(study())
    REPORT.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
