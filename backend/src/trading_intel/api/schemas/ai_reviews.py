"""Claude's exit advice as the dashboard sees it (D051). Shadow mode: it changed no trade."""

from typing import Literal

from pydantic import BaseModel

from trading_intel.core.clock import UtcDatetime

ReviewStatus = Literal["advised", "invalid", "refused", "error", "not_asked", "skipped_budget"]
ExitActionView = Literal["hold", "take_profit_now", "stop_to_breakeven"]


class ExitReviewView(BaseModel):
    close_time: UtcDatetime
    symbol: str
    strategy: str
    account: str
    checks: list[str]
    status: ReviewStatus
    action: ExitActionView | None
    reason: str | None
    progress_r: str  # The trade's R at the close it was asked about.
    model: str | None
    tokens: int
    cost_usd: str
    # Filled once the trade has finished: its R with its own exits and with the advice.
    own_r: str | None
    advised_r: str | None


class ExitReviewsView(BaseModel):
    shadow: Literal[True] = True
    model: str
    asking: bool  # False until an Anthropic key is set; checks are still counted.
    statuses: dict[str, int]
    cost_usd: str
    scored: int
    scored_not_hold: int
    # Mean R the advice added on finished trades, over answers that were not "hold".
    mean_change_r: str | None
    reviews: list[ExitReviewView]
