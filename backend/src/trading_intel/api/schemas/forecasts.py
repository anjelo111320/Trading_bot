"""The forecast view: Kronos beside its baseline, Python's levels and patterns, and the plan.

Forecast values are floats because they are model samples, not prices to trade. Market
prices and money stay strings, as everywhere else in the API.
"""

from typing import Literal

from pydantic import BaseModel, Field

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
    """Shares of paths that reach the level within this many candles of the latest close."""

    candles: int
    model: float | None  # Kronos, only while its forecast is from the latest close.
    baseline: float | None  # The projection. None when too few candles are stored.


class LevelView(BaseModel):
    id: str
    price: str
    kind: str
    position: Literal["above", "below"]
    evidence: str
    distance_atr: float  # From the latest close, in its 1H ATR.
    reach: list[ReachView]


class ProjectionStepView(BaseModel):
    open_time: UtcDatetime
    close: BandView  # Percentiles of the close across the baseline's paths at this candle.


class ProjectionHorizonView(BaseModel):
    candles: int
    baseline: SpreadView


class ProjectionView(BaseModel):
    """The baseline drawn again from the latest 1H close, so the chart's future starts now."""

    as_of: UtcDatetime
    last_close: str
    atr: float  # 1H ATR at the latest close.
    paths: int
    steps: list[ProjectionStepView]
    horizons: list[ProjectionHorizonView]


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


class ProposalView(BaseModel):
    """Prices Python calculated for a signal. Size and costs come from the risk engine."""

    side: str
    entry_type: str | None  # None in plans saved before it was recorded.
    entry: str
    stop: str
    targets: list[str]


class StrategyView(BaseModel):
    name: str
    action: str
    reasons: list[str]
    proposal: ProposalView | None = None  # Only with a BUY or SELL.


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
    # Python's signal at the plan's close, calculated before Claude planned. None when the
    # calculation was not saved beside the plan.
    python_at_close: list[StrategyView] | None


class ForecastView(BaseModel):
    label: str
    provider: str
    instrument_id: int
    symbol: str
    timeframe: Timeframe
    as_of: UtcDatetime  # The forecast's close: Kronos and the baseline drawn beside it.
    analysis_as_of: UtcDatetime  # The latest 1H close: levels, patterns, the projection.
    analysis_close: str
    forecast_current: bool  # The Kronos forecast is from the latest 1H close.
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
    projection: ProjectionView | None  # None when too few 1H candles are stored.
    levels: list[LevelView]
    patterns: list[ChartPatternView]
    candle_signals: list[CandleSignalView]
    context: MarketContextView
    track_record: TrackRecordView
    plan: PlanView | None


class AnalyseRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=40)
    instrument_id: int = Field(gt=0)


class AnalysisJobView(BaseModel):
    """The latest re-analysis. Only one runs at a time, because Kronos needs about 1 GB."""

    state: Literal["idle", "running", "succeeded", "failed"]
    instrument_id: int | None = None
    symbol: str | None = None
    as_of: UtcDatetime | None = None
    started_at: UtcDatetime | None = None
    finished_at: UtcDatetime | None = None
    message: str | None = None
