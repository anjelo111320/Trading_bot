"""Run the profit lock study once (docs/43): the live lock on four strategies' own entries.

Each filled trade is replayed through the shared simulator twice, with its own exits and with
the lock added, so every comparison is on the same entry. The lock decides at every 15-minute
fill close, the nearest the history allows to the live minute check. The rules and the decision
rule were pre-registered, and every window ends before the frozen holdout (D029).
"""

import argparse
import asyncio
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final

from trading_intel.backtesting.engine import (
    BacktestEngine,
    BacktestTrade,
    CostModel,
    TrailingStop,
    WindowedBaseline,
)
from trading_intel.backtesting.exits import ProfitLock, replay
from trading_intel.backtesting.metrics import bootstrap_interval
from trading_intel.backtesting.report import STATEMENT
from trading_intel.backtesting.windows import refuse_holdout
from trading_intel.domain.candles import ClosedCandle
from trading_intel.entrypoints import fvg_choch_backtest, pattern_backtest, trend_backtest
from trading_intel.entrypoints.new_coin_study import ALL_COINS, RULE_START, Remembered
from trading_intel.entrypoints.pattern_backtest import END, REPORT_DIR, START, Inputs, load
from trading_intel.trade_signals.baseline import STRATEGY_NAME as RULE_NAME
from trading_intel.trade_signals.baseline import BaselineParameters
from trading_intel.trade_signals.fvg_choch_strategy import STRATEGY_NAME as FVG_NAME
from trading_intel.trade_signals.fvg_choch_strategy import FvgChochStrategy
from trading_intel.trade_signals.pattern_strategy import STRATEGY_NAME as PATTERN_NAME
from trading_intel.trade_signals.pattern_strategy import PatternStrategy
from trading_intel.trade_signals.trend_strategy import STRATEGY_NAME as TREND_NAME
from trading_intel.trade_signals.trend_strategy import DailyTrendStrategy

STRATEGIES: Final = (TREND_NAME, PATTERN_NAME, FVG_NAME, RULE_NAME)
LEVELS: Final = ("1", "2")
REPORT: Final = REPORT_DIR / "profit-lock.md"

Runner = Callable[[str], list[BacktestTrade]]


@dataclass(frozen=True)
class Paired:
    """One filled trade's R with its own exits and with the lock, on the same entry."""

    strategy: str
    coin: str
    level: str
    own: float
    locked: float
    acted: bool

    @property
    def change(self) -> float:
        return self.locked - self.own


@dataclass
class Study:
    pairs: list[Paired] = field(default_factory=list)
    replayed: int = 0
    mismatched: int = 0


@dataclass(frozen=True)
class Plan:
    strategy: str
    setup: list[ClosedCandle]
    trail: TrailingStop | None
    run: Runner


def _plans(inputs: Inputs) -> list[Plan]:
    """Each strategy with the parameters that trade live, its setup candles and its runner."""
    tick = inputs.rules.tick_size
    trend = DailyTrendStrategy(inputs.days, tick, trend_backtest.PARAMETERS)
    pattern = PatternStrategy(inputs.hours, inputs.four_hours, inputs.days, tick)
    gap = FvgChochStrategy(inputs.fills, inputs.four_hours, tick, fvg_choch_backtest.PARAMETERS)
    rule = Remembered(
        WindowedBaseline(inputs.fills, inputs.hours, inputs.four_hours, tick, BaselineParameters())
    )

    def rule_run(level: str) -> list[BacktestTrade]:
        engine = BacktestEngine(
            inputs.instrument, inputs.rules, inputs.fills, inputs.fills, inputs.hours,
            inputs.four_hours, inputs.funding, costs=CostModel().stressed(level),
            strategy=rule, skip_signals_in_trade=True,
        )  # fmt: skip
        return engine.run(RULE_START, END).trades

    return [
        Plan(
            TREND_NAME, inputs.days, trend.trailing_stop,
            lambda level: trend_backtest.run(inputs, trend, level).trades,
        ),
        Plan(
            PATTERN_NAME, inputs.hours, None,
            lambda level: pattern_backtest.run(inputs, pattern, level).trades,
        ),
        Plan(
            FVG_NAME, inputs.fills, None,
            lambda level: fvg_choch_backtest.run(inputs, gap, level).trades,
        ),
        Plan(RULE_NAME, inputs.fills, None, rule_run),
    ]  # fmt: skip


def study_coin(inputs: Inputs, study: Study) -> None:
    open_times = [candle.open_time for candle in inputs.fills]
    every_close = {candle.close_time: candle.close for candle in inputs.fills}
    lock = ProfitLock(inputs.rules.tick_size)
    for plan in _plans(inputs):
        closes = {candle.close_time: candle.close for candle in plan.setup}
        for level in LEVELS:
            for trade in plan.run(level):
                own = replay(
                    trade.order, trade.signal_time, inputs.fills, open_times, closes,
                    inputs.funding, END, trail=plan.trail,
                )  # fmt: skip
                study.replayed += 1
                study.mismatched += own.result != trade.result
                locked = replay(
                    trade.order, trade.signal_time, inputs.fills, open_times, closes,
                    inputs.funding, END, trail=plan.trail, rule=lock, rule_closes=every_close,
                )  # fmt: skip
                planned = trade.planned_risk
                study.pairs.append(
                    Paired(
                        plan.strategy, inputs.symbol, level,
                        float(trade.result.net_pnl / planned),
                        float(locked.result.net_pnl / planned), locked.acted,
                    )
                )  # fmt: skip


def _pairs(study: Study, strategy: str | None, level: str = "1") -> list[Paired]:
    return [
        p for p in study.pairs if (strategy is None or p.strategy == strategy) and p.level == level
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
    locked: float | None
    change: float | None
    interval: tuple[float, float] | None
    doubled: float | None
    saved: float  # R the lock kept on acted trades that did better with it.
    given_up: float  # R it cost on acted trades that did worse.

    @property
    def outcome(self) -> str:
        if self.interval is None:
            return "no trades"
        if self.interval[1] < 0:
            return "loses"
        if self.interval[0] > 0:
            return "helps"
        return "no clear effect"


def verdict(study: Study, strategy: str | None) -> Verdict:
    pairs = _pairs(study, strategy)
    changes = [p.change for p in pairs]
    acted = [p for p in pairs if p.acted]
    return Verdict(
        trades=len(pairs),
        acted=len(acted),
        own=_mean([p.own for p in pairs]),
        locked=_mean([p.locked for p in pairs]),
        change=_mean(changes),
        interval=bootstrap_interval(changes),
        doubled=_mean([p.change for p in _pairs(study, strategy, "2")]),
        saved=sum(p.change for p in acted if p.change > 0),
        given_up=-sum(p.change for p in acted if p.change < 0),
    )


def decision_lines(study: Study) -> list[str]:
    if study.mismatched:
        return [
            f"**Void.** {study.mismatched} replays with no rule did not match the engine, so "
            "nothing changes until the replay is fixed and the study is run again."
        ]
    lines = ["Applied as pre-registered.", ""]
    for strategy in STRATEGIES:
        outcome = verdict(study, strategy).outcome
        if outcome == "loses":
            lines.append(f"- `{strategy}`: the lock **loses**. It stops acting on this strategy.")
        elif outcome == "helps":
            lines.append(f"- `{strategy}`: the lock **helps**. It stays.")
        else:
            lines.append(f"- `{strategy}`: {outcome}. The lock stays, as the owner chose (D066).")
    return lines


def render(study: Study) -> str:
    lines = [
        "# Profit Lock Study",
        "",
        STATEMENT,
        "",
        "Pre-registered in [43-PROFIT-LOCK-STUDY.md](../43-PROFIT-LOCK-STUDY.md) and run once. "
        f"The tested strategies from {START:%Y-%m-%d}, or the coin's first candle, and the 15M "
        f"rule from {RULE_START:%Y-%m-%d}, to {END:%Y-%m-%d}. Ten coins, each a separate 10,000 "
        "account at 1% risk per trade. The lock decides at every 15-minute close.",
        "",
        f"Replays with no rule: {study.replayed:,}; matching the engine: "
        f"{study.replayed - study.mismatched:,}.",
        "",
        "## Change in R per trade, the lock minus own exits, 1x costs",
        "",
        "| Strategy | Trades | Lock acted | Own exits | With the lock | Change | 95% interval | "
        "Change at 2x costs | R kept where it helped | R given up where it hurt |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for strategy in (*STRATEGIES, None):
        v = verdict(study, strategy)
        label = f"`{strategy}`" if strategy else "**All four pooled**"
        lines.append(
            f"| {label} | {v.trades} | {v.acted} | {_value(v.own)} | {_value(v.locked)} | "
            f"{_value(v.change)} | {_band(v.interval)} | {_value(v.doubled)} | "
            f"{v.saved:+.1f} | {-v.given_up:+.1f} |"
        )
    lines += [
        "",
        "## By coin, change in R per trade at 1x costs",
        "",
        "| Coin | " + " | ".join(STRATEGIES) + " |",
        "|---|" + "---|" * len(STRATEGIES),
    ]
    for coin in ALL_COINS:
        cells = []
        for strategy in STRATEGIES:
            changes = [p.change for p in _pairs(study, strategy) if p.coin == coin]
            cells.append(f"{_value(_mean(changes))} ({len(changes)})" if changes else "n/a")
        lines.append(f"| {coin} | " + " | ".join(cells) + " |")
    lines += ["", "## Decision", "", *decision_lines(study), "", "## Limits", ""]
    lines += [
        "- Fills are 15-minute candles. The live lock reads the mark price every minute, so the "
        "test sees candle extremes the live lock may miss, and it takes the stop first when a "
        "stop and the lock trigger fall in one candle.",
        "- The 15M rule is tested on two years only, on 15-minute fills (docs/42).",
        "- The coins move together, so the intervals are narrower than they should be.",
        "- A result is not proof of future profit.",
        "",
    ]
    return "\n".join(lines)


async def study() -> str:
    refuse_holdout(START, END)
    refuse_holdout(RULE_START, END)
    result = Study()
    for symbol in ALL_COINS:
        # One coin at a time, keeping only the paired results, so memory stays small.
        study_coin(await load(symbol), result)
        print(f"{symbol} done", flush=True)
    return render(result)


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    started = datetime.now(UTC)
    text = asyncio.run(study())
    REPORT.write_text(text)
    print(text)
    print(f"took {datetime.now(UTC) - started}")


if __name__ == "__main__":
    main()
