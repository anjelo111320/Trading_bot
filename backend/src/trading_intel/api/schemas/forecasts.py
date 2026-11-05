"""The forecast view: Kronos beside its baseline, Python's levels and patterns, and the plan.

Forecast values are floats because they are model samples, not prices to trade. Market
prices and money stay strings, as everywhere else in the API.
"""

from typing import Literal

from pydantic import BaseModel

from trading_intel.core.clock import UtcDatetime
from trading_intel.domain.candles import Timeframe


class BandView(BaseModel):
    p10: float
    p50: float
    p90: float


class ForecastStepView(BaseModel):
    open_time: UtcDatetime
    model: BandView  # Percentiles of the close across Kronos's paths at this candle.
    baseline: BandView


class SpreadView(BaseModel):
    share_ending_higher: float
    highest: BandView  # Percentiles of the highest price each path reaches, as prices.
    lowest: BandView
    close: BandView


class HorizonView(BaseModel):
    candles: int
    model: SpreadView
    baseline: SpreadView


class ReachView(BaseModel):
    candles: int
    model: float  # Share of paths that reach the level within this many candles.
    baseline: float


class LevelView(BaseModel):
    id: str
    price: str
    kind: str
    position: Literal["above", "below"]
    evidence: str
    distance_atr: float
    reach: list[ReachView]


class PatternPointView(BaseModel):
    name: str
    time: UtcDatetime
    price: float


class ChartPatternView(BaseModel):
    type: str
    direction: str
    breakout_at: UtcDatetime
    points: list[PatternPointView]
    invalidation: float | None
    measured_moves: list[float]
    invalidated_at: UtcDatetime | None
    decision: str
    reasons: list[str]


class CandleSignalView(BaseModel):
    type: str
    direction: str
    open_time: UtcDatetime


class StrategyView(BaseModel):
    name: str
    action: str
    reasons: list[str]


class MarketContextView(BaseModel):
    trend_4h: str
    trend_1d: str
    regime_trend: str
    regime_volatility: str
    adx_1d: float | None
    volatility_percentile: float | None
    rsi_1h: float | None
    rsi_4h: float | None
    strategies: list[StrategyView]


class TrackRecordView(BaseModel):
    resolved: int
    status: str
    brier_model: float | None
    brier_baseline: float | None
    crps_model_pct: float | None
    crps_baseline_pct: float | None


class PlanStatusView(BaseModel):
    state: Literal["waiting", "open", "closed", "not_filled"]
    exit_reason: str | None
    entry_price: str | None
    entry_time: UtcDatetime | None
    exit_price: str | None
    exit_time: UtcDatetime | None
    net_pnl: str | None
    result_r: float | None
    checked_until: UtcDatetime | None


class PlanView(BaseModel):
    source: str  # Where the plan came from. A manual test is labelled as one.
    created_at: UtcDatetime
    as_of: UtcDatetime
    expires_at: UtcDatetime
    action: str
    side: str
    entry_type: str
    entry: str
    stop: str
    targets: list[str]
    entry_level_id: str | None  # The catalogue levels the analyst chose, by ID (D009).
    stop_level_id: str | None
    target_level_ids: list[str]
    grade: str
    approved: bool
    rejection_codes: list[str]
    quantity: str | None
    max_loss: str | None
    reward_risk: list[str]
    bull_case: str
    bear_case: str
    pre_mortem: str
    note: str
    status: PlanStatusView


class ForecastView(BaseModel):
    label: str
    provider: str
    instrument_id: int
    symbol: str
    timeframe: Timeframe
    as_of: UtcDatetime
    created_at: UtcDatetime
    reason: str
    model: str
    model_revision: str
    last_close: str
    atr: float
    model_paths: int
    baseline_paths: int
    baseline_rebuilt: bool  # The baseline drawn here matched the stored one exactly.
    steps: list[ForecastStepView]
    paths: list[list[float]]  # Kronos's sampled closes, one list per path.
    horizons: list[HorizonView]
    levels: list[LevelView]
    patterns: list[ChartPatternView]
    candle_signals: list[CandleSignalView]
    context: MarketContextView
    track_record: TrackRecordView
    plan: PlanView | None
