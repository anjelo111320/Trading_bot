"""Assemble the forecast view: what Kronos and its baseline say, beside what Python sees.

Read-only. Levels, patterns and the baseline are recomputed from stored candles at the
forecast's close, so the page shows what was known then. A manual analyst plan, when one
exists, is replayed through the shared execution simulator on the candles that followed.
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
from trading_intel.risk_management.models import RiskProfile
from trading_intel.technical_analysis.momentum import rsi
from trading_intel.technical_analysis.series import CandleSeries, FloatArray
from trading_intel.trade_signals.catalogue import build_catalogue
from trading_intel.trade_signals.pattern_strategy import PatternStrategy
from trading_intel.trade_signals.trend_strategy import DailyTrendStrategy

SHORT_HORIZON: Final = 4  # The 4-hour test window, in 1H candles.
PATTERN_HOURS: Final = 72
SIGNAL_HOURS: Final = 24
LEVELS_PER_SIDE: Final = 5
CATALOGUE_CANDLES: Final = 400
SETUP: Final = Timeframe.H1
PlanState = Literal["waiting", "open", "closed", "not_filled"]
STATES: Final[dict[OrderStatus, PlanState]] = {
    OrderStatus.PENDING: "waiting",
    OrderStatus.OPEN: "open",
    OrderStatus.CLOSED: "closed",
    OrderStatus.CANCELLED: "not_filled",
}


@dataclass(frozen=True)
class MarketInputs:
    hours: list[ClosedCandle]  # 60 days of 1H candles closed by the forecast's close.
    fours: list[ClosedCandle]
    days: list[ClosedCandle]
    baseline_history: list[ClosedCandle]  # The candles the stored baseline was built from.
    tick: Decimal
    lot_step: Decimal


@dataclass(frozen=True)
class ManualPlan:
    signal: dict[str, Any]
    atr: float | None  # From the context the analyst read, when it was saved beside the plan.


def _price(value: Decimal | str) -> str:
    """A price for display: plain notation without the stored trailing zeros."""
    return plain(Decimal(value).normalize())


def load_manual_plan(directory: Path, symbol: str) -> ManualPlan | None:
    """The newest saved plan for a symbol. File names come from a fixed pattern only."""
    if not symbol.isalnum() or not directory.is_dir():
        return None
    files = sorted(directory.glob(f"{symbol}-*-signal.json"))
    if not files:
        return None
    signal = json.loads(files[-1].read_text())
    context_file = files[-1].with_name(files[-1].name.replace("-signal.json", "-context.json"))
    atr = None
    if context_file.exists():
        atr = float(json.loads(context_file.read_text())["snapshot"]["atr_1h"])
    return ManualPlan(signal, atr)


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
            name="1H pattern breakout",
            action=pattern_now.action.value,
            reasons=list(pattern_now.reasons),
        ),
        StrategyView(
            name="Daily trend", action=trend_now.action.value, reasons=list(trend_now.reasons)
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
    plan: ManualPlan, quarters: Sequence[ClosedCandle], market: MarketInputs, atr: float
) -> PlanStatusView:
    """Replay the plan on 15M candles that opened after it existed, as the backtester does."""
    signal = plan.signal
    proposal, risk, quote = signal["proposal"], signal["risk"], signal["quote"]
    as_of = datetime.fromisoformat(signal["as_of"])
    targets = tuple(Decimal(t) for t in proposal["targets"])
    costs = CostModel()
    slippage = costs.slippage(market.tick, Decimal(str(plan.atr or atr)))
    simulator = TradeSimulator(
        SimulatedOrder(
            side=Side(proposal["side"]),
            entry_type=EntryType(proposal["entry_type"]),
            entry=Decimal(proposal["entry"]),
            stop=Decimal(proposal["stop"]),
            targets=targets,
            allocation=scaled_allocation(RiskProfile().target_allocation, len(targets)),
            quantity=Decimal(risk["quantity"]),
            tick=market.tick,
            lot_step=market.lot_step,
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
    )


def build_view(
    *,
    provider: str,
    symbol: str,
    stored: StoredForecast,
    paths: list[Any],
    market: MarketInputs,
    record: TrackRecord,
    plan: PlanView | None,
) -> ForecastView:
    key = stored.key
    as_of, last_close = key.as_of, float(stored.last_close)
    model = SampledPaths(key.model, key.timeframe, as_of, last_close, np.array(paths, dtype=float))
    history = CandleSeries.of(market.baseline_history)
    parameters = TimeMachineParameters(
        **{k: v for k, v in stored.baseline["parameters"].items() if k != "version"}
    )
    baseline = time_machine(history, key.horizon_candles, parameters)
    rebuilt = summarise(baseline).as_json() == stored.baseline["summary"]

    starts = [
        SETUP.next_open(SETUP.floor(as_of)) + SETUP.delta * i for i in range(key.horizon_candles)
    ]
    steps = [
        ForecastStepView(
            open_time=start,
            model=_band(model.candles[:, i, CLOSE]),
            baseline=_band(baseline.candles[:, i, CLOSE]),
        )
        for i, start in enumerate(starts)
    ]
    windows = sorted({SHORT_HORIZON, key.horizon_candles})
    summaries = {n: (_cut(model, n), _cut(baseline, n)) for n in windows}

    strategy = PatternStrategy(market.hours, market.fours, market.days, market.tick)
    series = strategy.series
    window = series.window(len(series) - CATALOGUE_CANDLES, len(series))
    catalogue = build_catalogue(
        window, find_swings(window), strategy.atr[-CATALOGUE_CANDLES:], market.tick
    )
    nearby = (
        []
        if catalogue is None
        else [*catalogue.above()[:LEVELS_PER_SIDE], *catalogue.below()[:LEVELS_PER_SIDE]]
    )
    levels = [
        LevelView(
            id=level.id,
            price=_price(level.price),
            kind=level.kind,
            position=level.position,
            evidence=level.evidence,
            distance_atr=round((float(level.price) - last_close) / stored.atr, 2),
            reach=[
                ReachView(
                    candles=n,
                    model=round(reach_share(m, float(level.price), last_close), 3),
                    baseline=round(reach_share(b, float(level.price), last_close), 3),
                )
                for n, (m, b) in summaries.items()
            ],
        )
        for level in nearby
    ]
    return ForecastView(
        label=LABEL,
        provider=provider,
        instrument_id=key.instrument_id,
        symbol=symbol,
        timeframe=key.timeframe,
        as_of=as_of,
        created_at=stored.created_at,
        reason=stored.reason,
        model=key.model,
        model_revision=key.model_revision,
        last_close=_price(stored.last_close),
        atr=stored.atr,
        model_paths=model.count,
        baseline_paths=baseline.count,
        baseline_rebuilt=rebuilt,
        steps=steps,
        paths=[[float(f"{v:.8g}") for v in path] for path in model.candles[:, :, CLOSE]],
        horizons=[
            HorizonView(candles=n, model=_spread(m), baseline=_spread(b))
            for n, (m, b) in summaries.items()
        ],
        levels=levels,
        patterns=_patterns(strategy, as_of),
        candle_signals=_candle_signals(strategy, as_of),
        context=_context(
            strategy, DailyTrendStrategy(market.days, market.tick), market.fours, as_of
        ),
        track_record=_track(record),
        plan=plan,
    )
