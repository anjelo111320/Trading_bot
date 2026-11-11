"""Binance demo trading as the dashboard sees it (D048). Test funds only."""

from typing import Literal

from pydantic import BaseModel

from trading_intel.core.clock import UtcDatetime


class ExchangePositionView(BaseModel):
    symbol: str
    side: str
    quantity: str
    entry_price: str
    mark_price: str
    notional: str
    margin: str
    unrealized: str
    liquidation: str | None


class ExchangeOpenOrderView(BaseModel):
    """A stop or take-profit Binance holds. A stop closes the whole position."""

    symbol: str
    type: str
    side: str
    trigger: str
    quantity: str | None
    close_position: bool


class ExchangeStatusView(BaseModel):
    test_funds: Literal[True] = True
    connected: bool  # False until the quant worker has saved a snapshot.
    taken_at: UtcDatetime | None = None
    age_seconds: int | None = None
    binance_equity: str | None = None
    binance_available: str | None = None
    # The bot trades a fixed capital plus its own profit and loss, not all the test funds.
    capital: str
    equity: str | None = None
    day_start_equity: str | None = None
    available: str | None = None
    # Equity at which new trades stop for good, and when that happened (D053).
    loss_floor: str | None = None
    loss_stopped_at: UtcDatetime | None = None
    positions: list[ExchangePositionView] = []
    orders: list[ExchangeOpenOrderView] = []


class ExchangeOrderView(BaseModel):
    """One request sent to Binance and its outcome."""

    created_at: UtcDatetime
    symbol: str
    kind: str
    side: str | None
    type: str | None
    quantity: str | None
    trigger: str | None
    executed: str | None
    average_price: str | None
    outcome: Literal["accepted", "refused", "no reply"]
    error: str | None
