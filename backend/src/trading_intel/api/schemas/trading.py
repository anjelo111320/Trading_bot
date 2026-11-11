"""Signals and simulated trading. Money is a string, and every result is labelled simulated."""

from typing import Any, Literal

from pydantic import BaseModel

from trading_intel.core.clock import UtcDatetime
from trading_intel.domain.candles import Timeframe


class TargetView(BaseModel):
    price: str
    allocation: str
    net_reward_risk: str


class SignalScoreView(BaseModel):
    """The signal score's conditions at the signal: True for the trade, False against it,
    None unknown. The score failed its test (D046), so it is information and sets no size."""

    version: int
    weak: bool | None
    against: int
    long_term_trend: bool | None
    bitcoin_trend: bool | None
    bitcoin_applies: bool
    volume: bool | None
    funding: bool | None


class SignalView(BaseModel):
    id: str
    provider: str
    strategy: str
    instrument_id: int
    timeframe: Timeframe
    action: str
    entry_type: str | None
    state: str
    market_price: str
    entry_price: str | None
    stop_loss: str | None
    targets: list[TargetView]
    quantity: str | None
    notional: str | None
    max_account_risk: str | None
    estimated_fees: str | None
    estimated_funding: str | None
    reward_risk_net: str | None
    # The money plan's share of the 1% risk per trade (D045). None outside the plan.
    risk_share: str | None
    # None for signals recorded before the score was stored, on 2026-11-10.
    signal_score: SignalScoreView | None = None
    decision: str
    rejection_codes: list[str]
    setup_quality_score: str | None
    news_alignment: str
    data_reliability_score: str
    probability_status: str
    technical_explanation: str
    fundamental_explanation: str
    supporting_evidence: list[Any]
    conflicting_evidence: list[Any]
    invalidation_conditions: list[Any]
    created_at: UtcDatetime
    expires_at: UtcDatetime
    data_as_of: UtcDatetime


class PositionView(BaseModel):
    id: str
    symbol: str
    side: str
    status: str
    planned_quantity: str
    open_quantity: str
    average_entry: str | None
    stop_loss: str | None
    realized_pnl: str
    costs_paid: str
    opened_at: UtcDatetime | None
    closed_at: UtcDatetime | None
    signal_state: str | None
    reconstructed: bool


class FillView(BaseModel):
    kind: str
    at: UtcDatetime
    price: str | None
    quantity: str
    fee: str
    funding: str
    reconstructed: bool


class TradeView(BaseModel):
    """One simulated trade with its plan and every fill, for chart markers and history."""

    simulated: Literal[True] = True
    id: str
    instrument_id: int
    symbol: str
    strategy: str
    timeframe: Timeframe
    side: str
    status: str
    signal_state: str | None
    created_at: UtcDatetime
    expires_at: UtcDatetime
    planned_entry: str
    average_entry: str | None
    stop_loss: str
    current_stop: str
    targets: list[str]
    planned_quantity: str
    open_quantity: str
    realized_pnl: str
    costs_paid: str
    opened_at: UtcDatetime | None
    closed_at: UtcDatetime | None
    outcome: str | None
    r_multiple: str | None
    explanation: str
    max_account_risk: str | None
    # The money plan's share of the 1% risk, and what the strategy's evidence asked for (D045).
    risk_share: str | None
    evidence_share: str | None
    fills: list[FillView]


class PaperSummary(BaseModel):
    simulated: Literal[True] = True
    account: str
    starting_balance: str
    equity: str
    open_positions: int
    resolved_trades: int
    wins: int
    losses: int
    unfilled: int
    net_pnl: str
    costs: str
    win_rate: float | None
    expectancy_r: float | None
    # Today's start, what open trades could lose, and the money plan's limits (D045).
    day_start_equity: str
    open_risk: str
    max_open_risk: str | None
    daily_profit_stop: str | None


class NewsStoryView(BaseModel):
    headline: str
    published_at: UtcDatetime
    sentiment: str
    impact: str
    relevance: str
    weight: str  # Signed: what this story adds to the score.


class NewsSignalView(BaseModel):
    """A coin's news reading now, from Claude's labels, added up by Python (D055).

    Untested, and never read by any trade. Recorded at each 4H close to be tested.
    """

    untested: Literal[True] = True
    instrument_id: int
    at: UtcDatetime
    rule_version: int
    direction: Literal["bullish", "bearish", "neutral"]
    score: str
    threshold: str
    window_hours: int
    stories: list[NewsStoryView]


class NewsView(BaseModel):
    id: str
    headline: str
    source: str | None
    credibility_tier: str | None
    url: str
    published_at: UtcDatetime
    retrieved_at: UtcDatetime
    relevance: str | None
    event_type: str | None
    sentiment: str | None
    potential_impact: str | None
    certainty: str | None
    possibly_misleading: bool | None
    ai_summary: str | None
    classified: bool
