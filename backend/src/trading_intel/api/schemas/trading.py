"""Signals and simulated trading. Money is a string, and every result is labelled simulated."""

from typing import Any, Literal

from pydantic import BaseModel

from trading_intel.core.clock import UtcDatetime
from trading_intel.domain.candles import Timeframe


class TargetView(BaseModel):
    price: str
    allocation: str
    net_reward_risk: str


class SignalView(BaseModel):
    id: str
    provider: str
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


class PaperSummary(BaseModel):
    simulated: Literal[True] = True
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
