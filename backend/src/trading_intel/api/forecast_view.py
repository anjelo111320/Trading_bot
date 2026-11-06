"""Assemble the forecast view: what Kronos and its baseline say, beside what Python sees.

Read-only. Python's levels, patterns, decisions and the projection, the baseline drawn
again from the latest close, are computed at the latest stored 1H close, so they move on
every hour. Kronos and the baseline drawn beside it stay at the forecast's own close until
the next re-analysis. A manual analyst plan, when one exists, is replayed through the shared
execution simulator on the candles that followed.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Final, Literal

import numpy as np

from trading_intel.api.schemas.forecasts import (
    BandView,
    CandleSignalView,
    ChartPatternView,
    ForecastStepView,
    ForecastView,
    HorizonView,
    LevelView,
    MarketContextView,
    PatternPointView,
    PlanStatusView,
    PlanView,
    ProjectionHorizonView,
    ProjectionStepView,
    ProjectionView,
    ProposalView,
    ReachView,
    SpreadView,
    StrategyView,
    TrackRecordView,
)
from trading_intel.backtesting.engine import CostModel
from trading_intel.database.repositories.forecasts import StoredForecast
from trading_intel.domain.candles import ClosedCandle, Timeframe
from trading_intel.domain.events import plain
from trading_intel.domain.signals import EntryType, Side
from trading_intel.forecasting.evidence import LABEL
from trading_intel.forecasting.paths import CLOSE, SampledPaths
from trading_intel.forecasting.summary import Measure, PathSummary, reach_share, summarise
from trading_intel.forecasting.time_machine import TimeMachineParameters, time_machine
from trading_intel.forecasting.track_record import TrackRecord
from trading_intel.market_structure.swings import find_swings
from trading_intel.paper_trading.simulator import (
    OrderStatus,
    SimulatedOrder,
    TradeSimulator,
)
from trading_intel.paper_trading.simulator import (
    summarise as summarise_fills,
)
from trading_intel.pattern_detection.describe import describe
from trading_intel.risk_management.calculators.linear import scaled_allocation
from trading_intel.risk_management.models import RiskProfile, TradeProposal
from trading_intel.technical_analysis.momentum import rsi
from trading_intel.technical_analysis.series import CandleSeries, FloatArray
from trading_intel.trade_signals.catalogue import CatalogueLevel, build_catalogue
from trading_intel.trade_signals.pattern_strategy import PatternStrategy
from trading_intel.trade_signals.trend_strategy import DailyTrendStrategy

SHORT_HORIZON: Final = 4  # The 4-hour test window, in 1H candles.
PATTERN_HOURS: Final = 72
SIGNAL_HOURS: Final = 24
LEVELS_PER_SIDE: Final = 5
CATALOGUE_CANDLES: Final = 400
SETUP: Final = Timeframe.H1
PATTERN_STRATEGY: Final = "1H pattern breakout"
TREND_STRATEGY: Final = "Daily trend"
# Where a saved context records each strategy's decision at the plan's close.
SAVED_DECISIONS: Final = (
    ("pattern_strategy_now", PATTERN_STRATEGY),
    ("trend_strategy_now", TREND_STRATEGY),
)
PlanState = Literal["waiting", "open", "closed", "not_filled"]
STATES: Final[dict[OrderStatus, PlanState]] = {
    OrderStatus.PENDING: "waiting",
    OrderStatus.OPEN: "open",
    OrderStatus.CLOSED: "closed",
    OrderStatus.CANCELLED: "not_filled",
}


@dataclass(frozen=True)
class MarketInputs:
    hours: list[ClosedCandle]  # 60 days of 1H candles closed by the latest 1H close.
    fours: list[ClosedCandle]
    days: list[ClosedCandle]
    tick: Decimal
    lot_step: Decimal


@dataclass(frozen=True)
class ManualPlan:
    signal: dict[str, Any]
    atr: float | None  # From the context the analyst read, when it was saved beside the plan.
    python: list[StrategyView] | None  # Python's signal at the plan's close, from that context.


def _price(value: Decimal | str) -> str:
    """A price for display: plain notation without the stored trailing zeros."""
    return plain(Decimal(value).normalize())


def _proposal(proposal: TradeProposal | None) -> ProposalView | None:
    if proposal is None:
        return None
    return ProposalView(
        side=proposal.side.value,
        entry_type=proposal.entry_type.value,
        entry=_price(proposal.entry),
        stop=_price(proposal.stop),
        targets=[_price(target) for target in proposal.targets],
    )


def _saved_strategy(name: str, decision: dict[str, Any]) -> StrategyView:
    saved = decision.get("proposal")
    return StrategyView(
        name=name,
        action=decision["action"],
        reasons=list(decision["reasons"]),
        proposal=None
        if saved is None
        else ProposalView(
            side=saved["side"],
            entry_type=saved.get("entry_type"),
            entry=_price(saved["entry"]),
            stop=_price(saved["stop"]),
            targets=[_price(target) for target in saved["targets"]],
        ),
    )


def load_manual_plan(directory: Path, symbol: str) -> ManualPlan | None:
    """The newest saved plan for a symbol. File names come from a fixed pattern only.

    The context saved beside a plan is what Python calculated before the analyst read it,
    including each strategy's own signal at that close.
    """
    if not symbol.isalnum() or not directory.is_dir():
        return None
    files = sorted(directory.glob(f"{symbol}-*-signal.json"))
    if not files:
        return None
    signal = json.loads(files[-1].read_text())
    context_file = files[-1].with_name(files[-1].name.replace("-signal.json", "-context.json"))
    if not context_file.exists():
        return ManualPlan(signal, None, None)
    snapshot = json.loads(context_file.read_text())["snapshot"]
    python = [
        _saved_strategy(name, snapshot[key]) for key, name in SAVED_DECISIONS if key in snapshot
    ]
    return ManualPlan(signal, float(snapshot["atr_1h"]), python or None)


def _band(values: FloatArray) -> BandView:
    p10, p50, p90 = np.percentile(values, [10, 50, 90])
    return BandView(p10=float(p10), p50=float(p50), p90=float(p90))


def _spread(summary: PathSummary) -> SpreadView:
    def band(measure: Measure) -> BandView:
        return BandView(
            p10=summary.at(measure, 10), p50=summary.at(measure, 50), p90=summary.at(measure, 90)
        )

    return SpreadView(
        share_ending_higher=summary.share_higher,
        highest=band("high"),
        lowest=band("low"),
        close=band("close"),
    )


def _cut(paths: SampledPaths, candles: int) -> PathSummary:
    return summarise(
        SampledPaths(
            paths.source, paths.timeframe, paths.as_of, paths.last_close, paths.candles[:, :candles]
        )
    )


def _starts(as_of: datetime, horizon: int) -> list[datetime]:
    """Open times of the candles after a close."""
    first = SETUP.next_open(SETUP.floor(as_of))
    return [first + SETUP.delta * i for i in range(horizon)]


def stored_parameters(stored: StoredForecast) -> TimeMachineParameters:
    """The baseline settings the forecast was stored with."""
    return TimeMachineParameters(
        **{k: v for k, v in stored.baseline["parameters"].items() if k != "version"}
    )


def _track(record: TrackRecord) -> TrackRecordView:
    model, baseline = record.model, record.baseline
    return TrackRecordView(
        resolved=record.count,
        status=record.status,
        brier_model=None if model is None else model.brier,
        brier_baseline=None if baseline is None else baseline.brier,
        crps_model_pct=None if model is None else model.close_crps_pct,
        crps_baseline_pct=None if baseline is None else baseline.close_crps_pct,
    )


def _patterns(strategy: PatternStrategy, as_of: datetime) -> list[ChartPatternView]:
    found: list[ChartPatternView] = []
    for moment in sorted(strategy.breakouts):
        if not as_of - timedelta(hours=PATTERN_HOURS) <= moment <= as_of:
            continue
        decision = strategy.decide(moment)
        for pattern in strategy.breakouts[moment]:
            known = pattern.as_known_at(as_of)
            if known is None:
                continue
            facts = describe(known, strategy.series, strategy.atr) or {}
            names = [p["name"] for p in facts.get("points", [])]
            raw = known.evidence.get("points", [])
            points = [
                PatternPointView(
                    name=names[i] if i < len(names) else f"point {i + 1}",
                    time=SETUP.floor(datetime.fromisoformat(time)),
                    price=float(price),
                )
                for i, (time, price) in enumerate(raw)
            ]
            invalidation = known.evidence.get("invalidation")
            found.append(
                ChartPatternView(
                    type=known.pattern_type,
                    direction=known.direction.value,
                    breakout_at=SETUP.floor(known.detected_at),
                    points=points,
                    invalidation=None if invalidation is None else float(invalidation),
                    measured_moves=[float(m) for m in known.evidence.get("measured_moves", [])],
                    invalidated_at=known.invalidated_at,
                    decision=decision.action.value,
                    reasons=list(decision.reasons),
                )
            )
    return found


def _candle_signals(strategy: PatternStrategy, as_of: datetime) -> list[CandleSignalView]:
    return [
        CandleSignalView(
            type=p.pattern_type, direction=p.direction.value, open_time=SETUP.floor(moment)
        )
        for moment, found in sorted(strategy.candles.items())
        if as_of - timedelta(hours=SIGNAL_HOURS) <= moment <= as_of
        for p in found
    ]


def _context(
    strategy: PatternStrategy, trend: DailyTrendStrategy, fours: list[ClosedCandle], as_of: datetime
) -> MarketContextView:
    middle, higher = strategy.trends_at(as_of)
    regime = strategy.regimes.at(as_of)
    hourly, four_hourly = rsi(strategy.series.close), rsi(CandleSeries.of(fours).close)
    pattern_now = strategy.decide(as_of)
    trend_now = trend.decide(trend.series.close_time[-1])

    def finite(values: Any) -> float | None:
        value = float(values[-1])
        return None if value != value else round(value, 1)

    strategies = [
        StrategyView(
            name=PATTERN_STRATEGY,
            action=pattern_now.action.value,
            reasons=list(pattern_now.reasons),
            proposal=_proposal(pattern_now.proposal),
        ),
        StrategyView(
            name=TREND_STRATEGY,
            action=trend_now.action.value,
            reasons=list(trend_now.reasons),
            proposal=_proposal(trend_now.proposal),
        ),
    ]
    return MarketContextView(
        trend_4h=middle,
        trend_1d=higher,
        regime_trend=regime.trend,
        regime_volatility=regime.volatility,
        adx_1d=regime.adx,
        volatility_percentile=regime.volatility_percentile,
        rsi_1h=finite(hourly),
        rsi_4h=finite(four_hourly),
        strategies=strategies,
    )


def plan_status(
    plan: ManualPlan, quarters: Sequence[ClosedCandle], tick: Decimal, lot_step: Decimal, atr: float
) -> PlanStatusView:
    """Replay the plan on 15M candles that opened after it existed, as the backtester does."""
    signal = plan.signal
    proposal, risk, quote = signal["proposal"], signal["risk"], signal["quote"]
    as_of = datetime.fromisoformat(signal["as_of"])
    targets = tuple(Decimal(t) for t in proposal["targets"])
    costs = CostModel()
    slippage = costs.slippage(tick, Decimal(str(plan.atr or atr)))
    simulator = TradeSimulator(
        SimulatedOrder(
            side=Side(proposal["side"]),
            entry_type=EntryType(proposal["entry_type"]),
            entry=Decimal(proposal["entry"]),
            stop=Decimal(proposal["stop"]),
            targets=targets,
            allocation=scaled_allocation(RiskProfile().target_allocation, len(targets)),
            quantity=Decimal(risk["quantity"]),
            tick=tick,
            lot_step=lot_step,
            taker_fee=costs.taker_fee,
            maker_fee=costs.maker_fee,
            half_spread=(Decimal(quote["ask"]) - Decimal(quote["bid"])) / 2,
            entry_slippage=slippage,
            stop_slippage=slippage,
            placed_at=datetime.fromisoformat(signal["created_at"]),
            expires_at=as_of + SETUP.delta * int(proposal["expiry_candles"]),
        )
    )
    for candle in quarters:
        simulator.on_candle(candle)
        if simulator.is_finished:
            break
    result = summarise_fills(simulator.order.side, simulator.fills)
    state = STATES[simulator.status]
    loss = Decimal(risk["max_loss"]) if risk.get("max_loss") else None
    entered = result.entered
    return PlanStatusView(
        state=state,
        exit_reason=None if state in ("waiting", "open") else result.exit_reason,
        entry_price=None if result.entry_price is None else _price(result.entry_price),
        entry_time=result.entry_time,
        exit_price=None if result.exit_price is None else _price(result.exit_price),
        exit_time=result.exit_time,
        net_pnl=plain(result.net_pnl.quantize(Decimal("0.01"))) if entered else None,
        result_r=float(result.net_pnl / loss) if entered and loss else None,
        checked_until=quarters[-1].close_time if quarters else None,
    )


def plan_view(plan: ManualPlan, status: PlanStatusView) -> PlanView:
    signal = plan.signal
    proposal, risk, analyst = signal["proposal"], signal["risk"], signal["plan"]
    selection = analyst.get("selection") or {}
    as_of = datetime.fromisoformat(signal["as_of"])
    return PlanView(
        source="manual analyst test: a Claude Code session standing in for the API",
        created_at=datetime.fromisoformat(signal["created_at"]),
        as_of=as_of,
        expires_at=as_of
        + SETUP.delta * int(proposal["expiry_candles"])
        + timedelta(milliseconds=1),
        action=analyst["action"],
        side=proposal["side"],
        entry_type=proposal["entry_type"],
        entry=_price(proposal["entry"]),
        stop=_price(proposal["stop"]),
        targets=[_price(t) for t in proposal["targets"]],
        entry_level_id=selection.get("entry_level_id"),
        stop_level_id=selection.get("stop_level_id"),
        target_level_ids=list(selection.get("target_level_ids") or []),
        grade=analyst["setup_grade"],
        approved=bool(risk["approved"]),
        rejection_codes=list(risk["codes"]),
        quantity=None if risk.get("quantity") is None else _price(risk["quantity"]),
        max_loss=risk.get("max_loss"),
        reward_risk=list(risk.get("reward_risk_after_costs") or []),
        bull_case=analyst["bull_case"],
        bear_case=analyst["bear_case"],
        pre_mortem=analyst["pre_mortem"],
        note=analyst.get("analyst_note", ""),
        status=status,
        python_at_close=plan.python,
    )


@dataclass(frozen=True)
class ForecastPart:
    """Everything anchored at the forecast's close. It never changes for a stored forecast."""

    steps: list[ForecastStepView]
    paths: list[list[float]]
    summaries: dict[int, tuple[PathSummary, PathSummary]]  # Candles: (Kronos, baseline).
    model_paths: int
    baseline_paths: int
    rebuilt: bool


@dataclass(frozen=True)
class ProjectionPart:
    """The baseline drawn again from the latest close: how far price usually travels from here."""

    steps: list[ProjectionStepView]
    summaries: dict[int, PathSummary]  # Candles: summary.
    paths: int


@dataclass(frozen=True)
class AnalysisPart:
    """What Python sees at the latest 1H close. It changes once an hour."""

    as_of: datetime
    close: Decimal
    atr: float
    levels: list[CatalogueLevel]
    patterns: list[ChartPatternView]
    candle_signals: list[CandleSignalView]
    context: MarketContextView
    projection: ProjectionPart | None  # None when too few 1H candles are stored.


def forecast_part(
    stored: StoredForecast, paths: list[Any], baseline_history: list[ClosedCandle]
) -> ForecastPart:
    key = stored.key
    as_of, last_close = key.as_of, float(stored.last_close)
    model = SampledPaths(key.model, key.timeframe, as_of, last_close, np.array(paths, dtype=float))
    baseline = time_machine(
        CandleSeries.of(baseline_history), key.horizon_candles, stored_parameters(stored)
    )
    return ForecastPart(
        steps=[
            ForecastStepView(
                open_time=start,
                model=_band(model.candles[:, i, CLOSE]),
                baseline=_band(baseline.candles[:, i, CLOSE]),
            )
            for i, start in enumerate(_starts(as_of, key.horizon_candles))
        ],
        paths=[[float(f"{v:.8g}") for v in path] for path in model.candles[:, :, CLOSE]],
        summaries={
            n: (_cut(model, n), _cut(baseline, n))
            for n in sorted({SHORT_HORIZON, key.horizon_candles})
        },
        model_paths=model.count,
        baseline_paths=baseline.count,
        rebuilt=summarise(baseline).as_json() == stored.baseline["summary"],
    )


def projection_part(
    series: CandleSeries, parameters: TimeMachineParameters, horizon: int
) -> ProjectionPart | None:
    """The forecast's baseline settings, applied at the latest close."""
    if len(series) < parameters.lookback:
        return None
    paths = time_machine(series, horizon, parameters)
    return ProjectionPart(
        steps=[
            ProjectionStepView(open_time=start, close=_band(paths.candles[:, i, CLOSE]))
            for i, start in enumerate(_starts(paths.as_of, horizon))
        ],
        summaries={n: _cut(paths, n) for n in sorted({SHORT_HORIZON, horizon})},
        paths=paths.count,
    )


def analysis_part(
    market: MarketInputs, baseline: TimeMachineParameters, horizon: int
) -> AnalysisPart:
    strategy = PatternStrategy(market.hours, market.fours, market.days, market.tick)
    series = strategy.series
    as_of = series.close_time[-1]
    window = series.window(len(series) - CATALOGUE_CANDLES, len(series))
    catalogue = build_catalogue(
        window, find_swings(window), strategy.atr[-CATALOGUE_CANDLES:], market.tick
    )
    nearby = (
        []
        if catalogue is None
        else [*catalogue.above()[:LEVELS_PER_SIDE], *catalogue.below()[:LEVELS_PER_SIDE]]
    )
    return AnalysisPart(
        as_of=as_of,
        close=market.hours[-1].close,
        atr=float(strategy.atr[-1]),
        levels=nearby,
        patterns=_patterns(strategy, as_of),
        candle_signals=_candle_signals(strategy, as_of),
        context=_context(
            strategy, DailyTrendStrategy(market.days, market.tick), market.fours, as_of
        ),
        projection=projection_part(series, baseline, horizon),
    )


def _projection_view(analysis: AnalysisPart) -> ProjectionView | None:
    projection = analysis.projection
    if projection is None:
        return None
    return ProjectionView(
        as_of=analysis.as_of,
        last_close=_price(analysis.close),
        atr=analysis.atr,
        paths=projection.paths,
        steps=projection.steps,
        horizons=[
            ProjectionHorizonView(candles=n, baseline=_spread(summary))
            for n, summary in projection.summaries.items()
        ],
    )


def assemble(
    *,
    provider: str,
    symbol: str,
    stored: StoredForecast,
    forecast: ForecastPart,
    analysis: AnalysisPart,
    record: TrackRecord,
    plan: PlanView | None,
) -> ForecastView:
    """Join the two parts. Reach shares are measured from the latest close.

    Kronos's paths start at its own close, so its shares are given only while that is the
    latest close. Measured from an older close, they would describe a market that has moved.
    """
    key = stored.key
    last_close, close = float(stored.last_close), float(analysis.close)
    current = key.as_of == analysis.as_of
    projected = analysis.projection.summaries if analysis.projection else {}
    levels = [
        LevelView(
            id=level.id,
            price=_price(level.price),
            kind=level.kind,
            position=level.position,
            evidence=level.evidence,
            distance_atr=round((float(level.price) - close) / analysis.atr, 2),
            reach=[
                ReachView(
                    candles=n,
                    model=round(reach_share(m, float(level.price), last_close), 3)
                    if current
                    else None,
                    baseline=round(reach_share(projected[n], float(level.price), close), 3)
                    if n in projected
                    else None,
                )
                for n, (m, _) in forecast.summaries.items()
            ],
        )
        for level in analysis.levels
    ]
    return ForecastView(
        label=LABEL,
        provider=provider,
        instrument_id=key.instrument_id,
        symbol=symbol,
        timeframe=key.timeframe,
        as_of=key.as_of,
        analysis_as_of=analysis.as_of,
        analysis_close=_price(analysis.close),
        forecast_current=current,
        created_at=stored.created_at,
        reason=stored.reason,
        model=key.model,
        model_revision=key.model_revision,
        last_close=_price(stored.last_close),
        atr=stored.atr,
        model_paths=forecast.model_paths,
        baseline_paths=forecast.baseline_paths,
        baseline_rebuilt=forecast.rebuilt,
        steps=forecast.steps,
        paths=forecast.paths,
        horizons=[
            HorizonView(candles=n, model=_spread(m), baseline=_spread(b))
            for n, (m, b) in forecast.summaries.items()
        ],
        projection=_projection_view(analysis),
        levels=levels,
        patterns=analysis.patterns,
        candle_signals=analysis.candle_signals,
        context=analysis.context,
        track_record=_track(record),
        plan=plan,
    )
