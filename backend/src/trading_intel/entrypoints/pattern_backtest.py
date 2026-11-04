"""Backtest the pattern strategy on perpetual history from before the frozen holdout.

Runs both pre-registered trials at 1x, 1.5x and 2x costs, the random-entry benchmark and
buy and hold, then writes a Markdown report and the data behind the chart (D029, D034).
"""

import argparse
import asyncio
import json
import statistics
from bisect import bisect_left
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Final

from trading_intel.backtesting.analysis import (
    buy_and_hold,
    entered_between,
    exit_templates,
    group,
    metrics_for,
    pattern_of,
    side_of,
)
from trading_intel.backtesting.benchmarks import RandomTrendEntries
from trading_intel.backtesting.engine import (
    BacktestEngine,
    BacktestResult,
    BacktestTrade,
    CostModel,
    FundingEvent,
    Strategy,
)
from trading_intel.backtesting.metrics import Metrics
from trading_intel.backtesting.report import STATEMENT, metrics_table
from trading_intel.backtesting.windows import HOLDOUT_START, Fold, refuse_holdout, walk_forward
from trading_intel.core.settings import REPOSITORY_ROOT, load_settings
from trading_intel.database.engine import create_engine
from trading_intel.database.repositories.backtests import BacktestRunRepository
from trading_intel.database.repositories.candles import CandleRepository
from trading_intel.database.repositories.operations import MarketRepository, RuleRepository
from trading_intel.database.repositories.reference import ReferenceRepository
from trading_intel.database.repositories.signals import SignalRepository
from trading_intel.domain.candles import ClosedCandle, Timeframe
from trading_intel.domain.instruments import Instrument, InstrumentRules
from trading_intel.domain.patterns import RULE_VERSION, DetectedPattern
from trading_intel.domain.signals import Action
from trading_intel.entrypoints.wiring import git_sha
from trading_intel.market_structure.regime import RegimeView
from trading_intel.technical_analysis.series import CandleSeries
from trading_intel.trade_signals.pattern_strategy import (
    STRATEGY_NAME,
    STRATEGY_VERSION,
    PatternParameters,
    PatternStrategy,
)

START: Final = datetime(2020, 1, 1, tzinfo=UTC)
END: Final = HOLDOUT_START
LOAD_FROM: Final = datetime(2019, 1, 1, tzinfo=UTC)
STRESS: Final = ("1", "1.5", "2")
SEEDS: Final = range(1, 21)
TRIALS: Final = {1: PatternParameters(), 2: PatternParameters(require_candle=True)}
HOLDOUT_END: Final = HOLDOUT_START + timedelta(days=365)
VERSIONS: Final = {1: PatternParameters(), 2: PatternParameters(skip_volatile=True)}
BEFORE_ENTRY: Final = 40
MAX_BEFORE: Final = 160
AFTER_EXIT: Final = 15
MAX_CANDLES: Final = 320
NO_TRADE_EXAMPLES: Final = 4
DATA_DIR: Final = REPOSITORY_ROOT / "data" / "reports"
REPORT_DIR: Final = REPOSITORY_ROOT / "docs" / "reports"


@dataclass(frozen=True)
class Inputs:
    symbol: str
    instrument: Instrument
    rules: InstrumentRules
    fills: list[ClosedCandle]
    hours: list[ClosedCandle]
    four_hours: list[ClosedCandle]
    days: list[ClosedCandle]
    funding: list[FundingEvent]


async def load(symbol: str, end: datetime = END) -> Inputs:
    """Candles up to `end`. Callers check the window against the holdout first."""
    engine = create_engine(load_settings().database_url)
    listed = await ReferenceRepository(engine).provider_instruments("binance_usdm")
    item = next(entry for entry in listed if entry.instrument.symbol == symbol)
    provider, instrument = item.provider_id, item.instrument
    candles = CandleRepository(engine)
    rules = await RuleRepository(engine).current(provider, instrument.id)
    assert rules is not None, "instrument rules are required"

    async def candles_of(timeframe: Timeframe) -> list[ClosedCandle]:
        return await candles.range(provider, instrument.id, timeframe, LOAD_FROM, end)

    rows = await MarketRepository(engine).funding_between(provider, instrument.id, START, end)
    inputs = Inputs(
        symbol=symbol,
        instrument=instrument,
        rules=rules,
        fills=await candles_of(Timeframe.M15),
        hours=await candles_of(Timeframe.H1),
        four_hours=await candles_of(Timeframe.H4),
        days=await candles_of(Timeframe.D1),
        funding=[FundingEvent(at, rate, mark) for at, rate, mark in rows if mark is not None],
    )
    await engine.dispose()
    return inputs


def run(
    inputs: Inputs,
    strategy: Strategy,
    stress: str = "1",
    window: tuple[datetime, datetime] = (START, END),
) -> BacktestResult:
    return BacktestEngine(
        inputs.instrument,
        inputs.rules,
        inputs.fills,
        inputs.hours,
        inputs.four_hours,
        inputs.days,
        inputs.funding,
        costs=CostModel().stressed(stress),
        strategy=strategy,
        skip_signals_in_trade=True,
    ).run(*window)


def _outcome(reason: str) -> str:
    return "against the 4H or 1D trend" if "against the trend" in reason else reason


def funnel(strategy: PatternStrategy) -> tuple[Counter[str], list[tuple[datetime, str]]]:
    """What the strategy decided at every breakout, before any position or risk check."""
    outcomes: Counter[str] = Counter()
    refused: list[tuple[datetime, str]] = []
    for moment in sorted(strategy.breakouts):
        if not START <= moment < END:
            continue
        decision = strategy.decide(moment)
        if decision.action in (Action.BUY, Action.SELL):
            outcomes["proposed"] += 1
        else:
            outcomes[_outcome(decision.reasons[0])] += 1
            refused.append((moment, decision.reasons[0]))
    return outcomes, refused


def _value(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _days(start: datetime, end: datetime) -> int:
    return max((end - start).days, 1)


def _row(label: str, metrics: Metrics) -> str:
    interval = metrics.expectancy_interval
    band = f"{interval[0]:.2f} to {interval[1]:.2f}" if interval else "n/a"
    return (
        f"| {label} | {metrics.trades} | {_value(metrics.win_rate, 2)} | "
        f"{_value(metrics.expectancy_r, 3)} | {band} | {_value(metrics.profit_factor, 2)} | "
        f"{metrics.net_pnl:.0f} |"
    )


HEADER: Final = [
    "| | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Net P/L |",
    "|---|---|---|---|---|---|---|",
]


@dataclass(frozen=True)
class TrialRun:
    number: int
    strategy: PatternStrategy
    results: dict[str, BacktestResult]
    outcomes: Counter[str]
    refused: list[tuple[datetime, str]]


@dataclass(frozen=True)
class Benchmark:
    expectancies: list[float]
    trades: list[int]


def run_trial(inputs: Inputs, number: int) -> TrialRun:
    strategy = PatternStrategy(
        inputs.hours, inputs.four_hours, inputs.days, inputs.rules.tick_size, TRIALS[number]
    )
    results = {level: run(inputs, strategy, level) for level in STRESS}
    outcomes, refused = funnel(strategy)
    return TrialRun(number, strategy, results, outcomes, refused)


def run_benchmark(inputs: Inputs, trial: TrialRun) -> Benchmark | None:
    templates = exit_templates(trial.results["1"].trades)
    if not templates:
        return None
    expectancies: list[float] = []
    trades: list[int] = []
    for seed in SEEDS:
        entries = RandomTrendEntries(
            trial.strategy, templates, trial.outcomes["proposed"], seed, START, END
        )
        metrics = run(inputs, entries).metrics
        assert metrics is not None
        trades.append(metrics.trades)
        if metrics.expectancy_r is not None:
            expectancies.append(metrics.expectancy_r)
    return Benchmark(expectancies, trades)


def _test_folds() -> list[Fold]:
    return walk_forward(START, END)


def fold_lines(trades: Sequence[BacktestTrade]) -> tuple[list[str], list[BacktestTrade]]:
    lines = [*HEADER]
    tested: list[BacktestTrade] = []
    for fold in _test_folds():
        inside = entered_between(trades, fold.test_start, fold.test_end)
        tested += inside
        label = f"Fold {fold.number}: {fold.test_start:%Y-%m-%d} to {fold.test_end:%Y-%m-%d}"
        lines.append(_row(label, metrics_for(inside, _days(fold.test_start, fold.test_end))))
    folds = _test_folds()
    if folds:
        span = _days(folds[0].test_start, folds[-1].test_end)
        lines.append(_row("**All test folds**", metrics_for(tested, span)))
    return lines, tested


def gate_lines(
    tested: Sequence[BacktestTrade],
    stressed: Sequence[BacktestTrade],
    benchmark: Benchmark | None,
) -> list[str]:
    folds = _test_folds()
    span = _days(folds[0].test_start, folds[-1].test_end) if folds else 1
    main = metrics_for(tested, span)
    at_stress = metrics_for(stressed, span)
    by_fold = [metrics_for(entered_between(tested, f.test_start, f.test_end), 1) for f in folds]
    positive_folds = sum(1 for m in by_fold if m.trades and (m.expectancy_r or 0) > 0)
    interval = main.expectancy_interval
    beats = None
    if benchmark and benchmark.expectancies and main.expectancy_r is not None:
        ordered = sorted(benchmark.expectancies)
        beats = main.expectancy_r > ordered[int(len(ordered) * 0.95) - 1]

    def mark(passed: bool | None) -> str:
        return "n/a" if passed is None else ("Passed" if passed else "**Not met**")

    return [
        "| Gate | Required | Result | |",
        "|---|---|---|---|",
        f"| Out-of-sample trades | At least 200 | {main.trades} | {mark(main.trades >= 200)} |",
        f"| Expectancy | Interval above zero | "
        f"{_value(interval[0], 2) if interval else 'n/a'} to "
        f"{_value(interval[1], 2) if interval else 'n/a'} | "
        f"{mark(bool(interval and interval[0] > 0))} |",
        f"| Profit factor at 1.5x costs | Above 1.2 | {_value(at_stress.profit_factor, 2)} | "
        f"{mark((at_stress.profit_factor or 0) > 1.2)} |",
        f"| Positive folds | Most of {len(folds)} | {positive_folds} | "
        f"{mark(positive_folds > len(folds) / 2)} |",
        f"| Random benchmark | Above its 95th percentile | "
        f"{_value(main.expectancy_r, 3)} | {mark(beats)} |",
        "| Nearby parameters | Similar results | Not tested | n/a |",
    ]


def render(
    inputs: Inputs, trials: dict[int, TrialRun], benchmark: Benchmark | None, regimes: RegimeView
) -> str:
    first = trials[1]
    base = first.results["1"]
    assert base.metrics is not None
    hold = buy_and_hold(inputs.days, START, END)
    lines = [
        f"# Pattern Breakout Backtest: {inputs.symbol} Perpetual",
        "",
        STATEMENT,
        "",
        f"Strategy `{STRATEGY_NAME}` version {STRATEGY_VERSION}, pattern rule version "
        f"{RULE_VERSION}. Rules were registered before any run in "
        "[27-PATTERN-SIGNAL-PLAN.md](../27-PATTERN-SIGNAL-PLAN.md). Period "
        f"{START:%Y-%m-%d} to {END:%Y-%m-%d}, before the frozen holdout (D029). "
        f"Data: {len(inputs.hours):,} 1H, {len(inputs.four_hours):,} 4H, "
        f"{len(inputs.days):,} 1D and {len(inputs.fills):,} 15M candles, and "
        f"{len(inputs.funding):,} funding events.",
        "",
        "## Trial 1 at Normal Costs",
        "",
        *metrics_table(base.metrics),
        "",
        "## How Signals Were Made",
        "",
        "Every 1H candle where a chart pattern broke out, and what the strategy decided there.",
        "",
        "| Step | Count |",
        "|---|---|",
        f"| Chart-pattern breakouts | {first.outcomes.total()} |",
    ]
    lines += [
        f"| Refused: {reason} | {count} |"
        for reason, count in first.outcomes.most_common()
        if reason != "proposed"
    ]
    lines += [
        f"| Proposed as BUY or SELL | {first.outcomes['proposed']} |",
        f"| Reached the risk engine, with no position open | {base.signals} |",
        f"| Approved and filled | {len(base.trades)} |",
        "",
    ]
    if base.rejections:
        lines += ["Risk engine rejections:", ""]
        lines += [f"- {code.value}: {n}" for code, n in sorted(base.rejections.items())]
        lines.append("")
    lines += ["## Costs", "", *HEADER]
    for level in STRESS:
        metrics = first.results[level].metrics
        assert metrics is not None
        lines.append(_row(f"Trial 1 at {level}x costs", metrics))
    lines += ["", "## Walk-Forward Test Folds, Trial 1", ""]
    folds, tested = fold_lines(base.trades)
    stressed_tested = []
    for fold in _test_folds():
        stressed_tested += entered_between(
            first.results["1.5"].trades, fold.test_start, fold.test_end
        )
    lines += [*folds, "", "## Benchmarks", ""]
    lines.append(
        f"- Buy and hold, no costs: {hold:+.1%} over the period." if hold is not None else ""
    )
    if benchmark and benchmark.expectancies:
        ordered = sorted(benchmark.expectancies)
        lines.append(
            f"- Random entries with the 4H and 1D trend, same exits, {len(SEEDS)} seeds: mean "
            f"expectancy {statistics.fmean(ordered):.3f}R, 5th to 95th percentile "
            f"{ordered[int(len(ordered) * 0.05)]:.3f}R to "
            f"{ordered[int(len(ordered) * 0.95) - 1]:.3f}R, mean "
            f"{statistics.fmean(benchmark.trades):.0f} trades per seed. Strategy: "
            f"{_value(base.metrics.expectancy_r)}R."
        )
    lines += ["", "## By Pattern and Direction, Trial 1", "", *HEADER]
    for name, members in group(base.trades, pattern_of).items():
        lines.append(_row(name, metrics_for(members, _days(START, END))))
    for name, members in group(base.trades, side_of).items():
        lines.append(_row(name, metrics_for(members, _days(START, END))))
    lines += [
        "",
        "## By Market Regime at the Signal, Trial 1",
        "",
        "Daily ADX of 25 or more is trending, below 20 ranging. Volatility ranks daily ATR "
        "against the trailing year: calm is the lowest quarter, volatile the highest. Labels "
        "use only data known at the signal. These are descriptions of the past, and a rule "
        "built from them needs fresh data to test.",
        "",
        *HEADER,
    ]
    for prefix, read in (
        ("trend", lambda t: regimes.at(t.signal_time).trend),
        ("volatility", lambda t: regimes.at(t.signal_time).volatility),
    ):
        for name, members in group(base.trades, read).items():
            lines.append(_row(f"{prefix}: {name}", metrics_for(members, _days(START, END))))
    second = trials[2]
    lines += [
        "",
        "## Trial 2: Candle Confirmation Required",
        "",
        f"Breakouts: {second.outcomes.total()}. Proposed: {second.outcomes['proposed']}.",
        "",
        *HEADER,
    ]
    for level in STRESS:
        metrics = second.results[level].metrics
        assert metrics is not None
        lines.append(_row(f"Trial 2 at {level}x costs", metrics))
    second_folds, _ = fold_lines(second.results["1"].trades)
    lines += ["", "Walk-forward test folds at normal costs:", "", *second_folds]
    lines += [
        "",
        "## Promotion Gate, Trial 1",
        "",
        *gate_lines(tested, stressed_tested, benchmark),
        "",
        "## Limits",
        "",
        "- Two trials were run, both declared in advance. No parameter was tuned.",
        "- Fills use 15M candles, not 1M. A stop and target in the same candle count as a "
        "stop, so this can only make results worse (D034).",
        "- Spread and slippage are conservative assumptions. Instrument rules are today's "
        "snapshot, used as a proxy for the whole period.",
        "- One position at a time, and signals during an open trade are ignored. Runs are "
        "therefore path dependent: at higher costs the 2:1 rule rejects more marginal setups, "
        "which frees the position for other trades. On the trades two cost levels share, the "
        "higher cost always earns less.",
        "- Patterns are labels from written rules. Some shapes that pass a rule, such as a "
        "wedge whose last two turning points sit on neighbouring candles, would not be drawn "
        "that way by a person.",
        "- BTC and ETH were chosen with hindsight, which is survivorship bias.",
        "- No news was used. Claude is not part of this test (D030).",
        "",
    ]
    return "\n".join(lines)


def _epoch(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def _index_at(close_times: Sequence[datetime], moment: datetime) -> int:
    """The 1H candle containing `moment`."""
    return min(bisect_left(close_times, moment), len(close_times) - 1)


def _geometry(
    pattern: DetectedPattern, close_times: Sequence[datetime], offset: int
) -> dict[str, Any]:
    def points(raw: object) -> list[list[float]]:
        assert isinstance(raw, list)
        return [
            [_index_at(close_times, datetime.fromisoformat(when)) - offset, float(price)]
            for when, price in raw
        ]

    evidence = pattern.evidence
    shape: dict[str, Any] = {
        "type": pattern.pattern_type,
        "direction": pattern.direction.value,
        "strength": pattern.strength,
        "points": points(evidence["points"]),
        "trigger": evidence["trigger"],
        "invalidation": evidence["invalidation"],
        "measured_moves": evidence["measured_moves"],
        "detected": _index_at(close_times, pattern.detected_at) - offset,
    }
    for side in ("upper", "lower"):
        if side in evidence:
            shape[side] = points(evidence[side])
    return shape


def _candles(hours: Sequence[ClosedCandle], start: int, end: int) -> list[list[float]]:
    return [
        [_epoch(c.open_time), float(c.open), float(c.high), float(c.low), float(c.close)]
        for c in hours[start:end]
    ]


def trade_record(
    trade: BacktestTrade,
    hours: Sequence[ClosedCandle],
    close_times: Sequence[datetime],
    number: int,
    regime: str,
) -> dict[str, Any]:
    outcome, order, decision = trade.result, trade.order, trade.decision
    assert decision is not None and outcome.entry_time and outcome.exit_time
    signal = _index_at(close_times, trade.signal_time)
    exit_at = _index_at(close_times, outcome.exit_time)
    pattern = decision.patterns[0]
    formed = _index_at(close_times, pattern.formed_at)
    start = max(0, signal - MAX_BEFORE, min(signal - BEFORE_ENTRY, formed - 10))
    end = min(len(hours), exit_at + AFTER_EXIT + 1, start + MAX_CANDLES)
    return {
        "number": number,
        "signal_time": trade.signal_time.isoformat(),
        "side": order.side.value,
        "reason": decision.reasons[0],
        "regime": regime,
        "pattern": _geometry(pattern, close_times, start),
        "confirmation": decision.patterns[1].pattern_type if len(decision.patterns) > 1 else None,
        "entry_plan": float(order.entry),
        "stop": float(order.stop),
        "targets": [float(t) for t in order.targets],
        "signal_index": signal - start,
        "entry_price": float(outcome.entry_price or 0),
        "exit_price": float(outcome.exit_price or 0),
        "exit_index": exit_at - start,
        "exit_time": outcome.exit_time.isoformat(),
        "exit_reason": outcome.exit_reason,
        "r": float(outcome.net_pnl / trade.planned_risk) if trade.planned_risk else 0.0,
        "net_pnl": float(outcome.net_pnl),
        "fees": float(outcome.fees),
        "funding": float(outcome.funding),
        "candles": _candles(hours, start, end),
    }


def refused_record(
    strategy: PatternStrategy,
    hours: Sequence[ClosedCandle],
    close_times: Sequence[datetime],
    moment: datetime,
    reason: str,
) -> dict[str, Any] | None:
    decision = strategy.decide(moment)
    if not decision.patterns:
        return None
    pattern = decision.patterns[0]
    index = _index_at(close_times, moment)
    formed = _index_at(close_times, pattern.formed_at)
    start = max(0, index - MAX_BEFORE, min(index - BEFORE_ENTRY, formed - 10))
    end = min(len(hours), index + 40, start + MAX_CANDLES)
    middle, higher = strategy.trends_at(moment)
    return {
        "time": moment.isoformat(),
        "reason": reason,
        "trend_4h": middle,
        "trend_1d": higher,
        "pattern": _geometry(pattern, close_times, start),
        "signal_index": index - start,
        "candles": _candles(hours, start, end),
    }


def _spread(items: Sequence[Any], count: int) -> list[Any]:
    """Evenly spaced picks, so examples are not chosen by hand."""
    if len(items) <= count:
        return list(items)
    step = len(items) / count
    return [items[int(i * step)] for i in range(count)]


def chart_data(
    inputs: Inputs, trials: dict[int, TrialRun], benchmark: Benchmark | None, regimes: RegimeView
) -> dict[str, Any]:
    first = trials[1]
    base = first.results["1"]
    close_times = [c.close_time for c in inputs.hours]
    refused: list[dict[str, Any]] = []
    for reason in ("against the 4H or 1D trend", "no reachable target"):
        moments = [(m, r) for m, r in first.refused if _outcome(r) == reason]
        for moment, why in _spread(moments, NO_TRADE_EXAMPLES):
            record = refused_record(first.strategy, inputs.hours, close_times, moment, why)
            if record:
                refused.append(record)
    days = [c for c in inputs.days if c.open_time >= START and c.close_time < END]

    def equity(result: BacktestResult) -> list[list[float]]:
        return [[_epoch(at), float(value)] for at, value in result.equity]

    summary: dict[str, Any] = {}
    for number, trial in trials.items():
        for level in STRESS:
            metrics = trial.results[level].metrics
            assert metrics is not None
            summary[f"trial{number}_{level}x"] = {
                "trades": metrics.trades,
                "win_rate": metrics.win_rate,
                "expectancy_r": metrics.expectancy_r,
                "interval": metrics.expectancy_interval,
                "profit_factor": metrics.profit_factor,
                "net_pnl": float(metrics.net_pnl),
                "max_drawdown": metrics.max_drawdown,
            }
    return {
        "symbol": inputs.symbol,
        "statement": STATEMENT,
        "strategy": f"{STRATEGY_NAME} v{STRATEGY_VERSION}, rule version {RULE_VERSION}",
        "period": [START.isoformat(), END.isoformat()],
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "summary": summary,
        "funnel": dict(first.outcomes),
        "signals": base.signals,
        "rejections": {code.value: n for code, n in base.rejections.items()},
        "buy_and_hold": buy_and_hold(inputs.days, START, END),
        "benchmark": None
        if benchmark is None
        else {"expectancies": benchmark.expectancies, "trades": benchmark.trades},
        "equity": {
            "trial1_1x": equity(base),
            "trial1_2x": equity(first.results["2"]),
            "trial2_1x": equity(trials[2].results["1"]),
            "buy_and_hold": [
                [_epoch(c.close_time), float(10000 * c.close / days[0].open)] for c in days
            ]
            if days
            else [],
        },
        "trades": [
            trade_record(
                trade, inputs.hours, close_times, number, regimes.at(trade.signal_time).label
            )
            for number, trade in enumerate(base.trades, start=1)
        ],
        "refused": refused,
    }


def _decimal_default(value: object) -> object:
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(f"cannot serialise {type(value).__name__}")


async def backtest(symbol: str) -> str:
    refuse_holdout(START, END)
    inputs = await load(symbol)
    trials = {number: run_trial(inputs, number) for number in TRIALS}
    benchmark = run_benchmark(inputs, trials[1])
    regimes = RegimeView(CandleSeries.of(inputs.days))
    text = render(inputs, trials, benchmark, regimes)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"pattern-backtest-{symbol}.json"
    data = chart_data(inputs, trials, benchmark, regimes)
    path.write_text(json.dumps(data, default=_decimal_default))
    return text


def _holdout_row(symbol: str, version: int, level: str, metrics: Metrics) -> str:
    interval = metrics.expectancy_interval
    band = f"{interval[0]:.2f} to {interval[1]:.2f}" if interval else "n/a"
    return (
        f"| {symbol} | {version} | {level}x | {metrics.trades} | {_value(metrics.win_rate, 2)} | "
        f"{_value(metrics.expectancy_r, 3)} | {band} | {_value(metrics.profit_factor, 2)} | "
        f"{metrics.net_pnl:.0f} | {metrics.max_drawdown:.1%} |"
    )


async def holdout(symbols: Sequence[str]) -> str:
    """The single holdout run for each version (D029, D037). It can never be repeated."""
    refuse_holdout(HOLDOUT_START, HOLDOUT_END, holdout_run=True)
    engine = create_engine(load_settings().database_url)
    runs = BacktestRunRepository(engine)
    manifest = {
        "symbols": list(symbols),
        "timeframes": ["15m", "1h", "4h", "1d"],
        "window": [HOLDOUT_START.isoformat(), HOLDOUT_END.isoformat()],
    }
    dataset = await runs.ensure_dataset("perpetuals-holdout-2025-11-01", manifest)
    claims = {}
    for version, parameters in VERSIONS.items():
        strategy_id = await SignalRepository(engine).ensure_strategy(
            STRATEGY_NAME, version, parameters.as_dict()
        )
        claims[version] = await runs.start_holdout(
            strategy_id, dataset, (HOLDOUT_START, HOLDOUT_END), vars(CostModel()), git_sha()
        )
    lines = [
        "# Pattern Breakout Holdout Run",
        "",
        STATEMENT,
        "",
        f"The single holdout run for versions 1 and 2, {HOLDOUT_START:%Y-%m-%d} to "
        f"{HOLDOUT_END:%Y-%m-%d} (D029, D037). Nothing was tuned on this year. Version 2 is "
        "version 1 plus no new trade when daily volatility is in the highest quarter of its "
        "year, a rule found in 2020 to 2025 data.",
        "",
        "| Coin | Version | Costs | Trades | Win rate | Expectancy (R) | 95% interval | "
        "Profit factor | Net P/L | Max drawdown |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    results: dict[int, dict[str, Any]] = {version: {} for version in VERSIONS}
    holds: list[str] = []
    try:
        for symbol in symbols:
            inputs = await load(symbol, end=HOLDOUT_END)
            for version, parameters in VERSIONS.items():
                strategy = PatternStrategy(
                    inputs.hours, inputs.four_hours, inputs.days, inputs.rules.tick_size, parameters
                )
                for level in ("1", "2"):
                    metrics = run(inputs, strategy, level, (HOLDOUT_START, HOLDOUT_END)).metrics
                    assert metrics is not None
                    lines.append(_holdout_row(symbol, version, level, metrics))
                    results[version][f"{symbol}_{level}x"] = {
                        "trades": metrics.trades,
                        "expectancy_r": metrics.expectancy_r,
                        "profit_factor": metrics.profit_factor,
                        "net_pnl": float(metrics.net_pnl),
                    }
            hold = buy_and_hold(inputs.days, HOLDOUT_START, HOLDOUT_END)
            holds.append(f"{symbol} {hold:+.1%}" if hold is not None else f"{symbol} n/a")
    except Exception:
        for version, run_id in claims.items():
            await runs.finish(run_id, "failed", results[version])
        await engine.dispose()
        raise
    for version, run_id in claims.items():
        await runs.finish(run_id, "succeeded", results[version])
    await engine.dispose()
    lines += [
        "",
        f"Buy and hold over the same year, no costs: {', '.join(holds)}.",
        "",
        "## Limits",
        "",
        "- One year and a few dozen trades per coin and version. This is far short of the "
        "200 out-of-sample trades the promotion gate needs, so it is a check, not proof.",
        "- This holdout is now spent for both versions. A changed strategy needs fresh data, "
        "normally from forward paper trading.",
        "- Fills use 15M candles, costs are conservative assumptions, and BTC and ETH were "
        "chosen with hindsight.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT"])
    parser.add_argument(
        "--holdout",
        action="store_true",
        help="Run the single, unrepeatable holdout test for versions 1 and 2 (D037)",
    )
    arguments = parser.parse_args()
    if arguments.holdout:
        text = asyncio.run(holdout(arguments.symbols))
        (REPORT_DIR / "pattern-holdout.md").write_text(text)
        print(text)
        return
    for symbol in arguments.symbols:
        text = asyncio.run(backtest(symbol))
        name = symbol.removesuffix("USDT").lower()
        (REPORT_DIR / f"pattern-backtest-{name}.md").write_text(text)
        print(text)


if __name__ == "__main__":
    main()
