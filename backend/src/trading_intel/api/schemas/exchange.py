"""The bot's Binance accounts as the dashboard sees them: demo trading's test funds (D048) and
the owner's real futures wallet (D060)."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

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
    # False for a position the owner opened themselves on the real account: the bot leaves it.
    bot: bool = True


class ExchangeOpenOrderView(BaseModel):
    """A stop or take-profit Binance holds, or a waiting limit entry. A stop closes the whole
    position."""

    symbol: str
    type: str
    side: str
    trigger: str
    quantity: str | None
    close_position: bool
    bot: bool = True  # False for an order the owner placed themselves.


class LiveStateView(BaseModel):
    """The real account's arming and its hourly check with Binance (D060)."""

    armed: bool
    armed_at: UtcDatetime | None = None
    checked_at: UtcDatetime | None = None
    # Each one stops new trades: a key that can withdraw or transfer, hedge mode, and so on.
    problems: list[str] = []
    ip_restricted: bool | None = None


class ExchangeStatusView(BaseModel):
    test_funds: bool = True  # False on the real account.
    connected: bool  # False until the quant worker has saved a snapshot.
    taken_at: UtcDatetime | None = None
    age_seconds: int | None = None
    binance_equity: str | None = None
    binance_available: str | None = None
    # Demo trading trades a fixed capital plus its own profit and loss, not all the test
    # funds. On the real account the capital is what the owner put in the futures wallet.
    capital: str
    equity: str | None = None
    day_start_equity: str | None = None
    available: str | None = None
    # Equity at which new trades stop for good, and when that happened (D053).
    loss_floor: str | None = None
    loss_stopped_at: UtcDatetime | None = None
    positions: list[ExchangePositionView] = []
    orders: list[ExchangeOpenOrderView] = []
    live: LiveStateView | None = None
    closing: list[str] = []  # Coins with a close from the dashboard still being carried out.
    # Whether the account may open new trades: its switch on the Bot page (D063, D064).
    armed: bool = False


class CloseRequestView(BaseModel):
    """A close asked from the dashboard, which the quant worker carries out within seconds."""

    id: str
    symbol: str
    requested_at: UtcDatetime
    done_at: UtcDatetime | None = None
    outcome: Literal["closed", "nothing_open", "not_the_bots", "failed"] | None = None
    detail: str | None = None


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
    # What the order means in USDT (D057). On every order of a trade: the strategy that sent it.
    strategy: str | None = None
    value_usdt: str | None = None  # Size at the order's price.
    if_hit_usdt: str | None = None  # A stop's loss or a target's profit if it fills, before fees.
    # On the entry: profit now while open, or the net result once closed, and the trade's state.
    now_usdt: str | None = None
    trade_state: Literal["open", "won", "lost", "waiting", "not filled"] | None = None
    risk_usdt: str | None = None  # On the entry: what the risk engine planned to lose.
    fill_price: str | None = None  # On the entry: the price Binance filled it at.


class StatsView(BaseModel):
    """Results of a set of completed trades. Money in USDT; rates as fractions (0.5 is 50%)."""

    trades: int
    wins: int
    losses: int
    win_rate: str | None
    net: str  # Realized profit, less fees, plus funding.
    pnl: str
    fees: str
    funding: str
    average_r: str | None
    average_win: str | None
    average_loss: str | None
    profit_factor: str | None  # None when nothing was lost.
    best: str | None
    worst: str | None


class GroupView(BaseModel):
    name: str
    stats: StatsView


class GridCellView(BaseModel):
    strategy: str
    symbol: str
    stats: StatsView


class EquityPointView(BaseModel):
    at: UtcDatetime
    equity: str


class ClosedTradeView(BaseModel):
    symbol: str
    side: str
    strategy: str
    opened_at: UtcDatetime
    closed_at: UtcDatetime
    size: str
    entry_price: str | None
    exit_price: str | None
    pnl: str
    fees: str
    funding: str
    net: str
    r: str | None
    won: bool


class ResultsView(BaseModel):
    """A Binance account's completed trades, rebuilt from Binance's own fills (D057)."""

    test_funds: bool = True  # False on the real account (D060).
    period: Literal["7d", "30d", "all"]
    since: UtcDatetime
    start_equity: str
    summary: StatsView
    by_coin: list[GroupView]
    by_strategy: list[GroupView]
    by_side: list[GroupView]
    by_day: list[GroupView]
    grid: list[GridCellView]
    equity: list[EquityPointView]
    drawdown: str
    drawdown_fraction: str | None
    longest_wins: int
    longest_losses: int
    current_streak: int  # Positive for a winning run, negative for a losing run.
    median_hold_hours: str | None
    open_trades: int
    not_from_bot: int  # Completed trades no entry of the bot's opened, left out.
    other_fees: dict[str, str]  # Fees in an asset other than USDT, left out of net.
    last_fill_at: UtcDatetime | None
    trades: list[ClosedTradeView]


class LimitCeilingsView(BaseModel):
    """The risk engine's hard ceilings, which no setting can pass."""

    risk_per_trade: str
    open_risk: str
    daily_loss: str
    leverage: str
    exposure: str


class LimitsView(BaseModel):
    """A Binance account's limits as the risk engine uses them (D058). Fractions: 0.1 is 10%."""

    version: int
    changed_at: UtcDatetime
    risk_per_trade: str
    open_risk: str | None
    exposure: str  # All positions together, as a share of equity.
    largest_trade: str | None = None  # One position at most, as a share of equity (D061).
    # Longs together, or shorts together, at most this share of equity (D072).
    one_direction: str | None = None
    max_leverage: str
    daily_loss: str
    daily_profit_stop: str | None  # None: no daily profit stop.
    loss_stop: str | None  # None: no loss stop.
    loss_stop_from_high: bool
    ceilings: LimitCeilingsView


class LimitsUpdate(BaseModel):
    """New limits from the owner. Each becomes a new version; ceilings still apply."""

    model_config = {"extra": "forbid"}

    risk_per_trade: Decimal
    open_risk: Decimal
    exposure: Decimal
    largest_trade: Decimal | None = None  # None: no limit on one position alone.
    one_direction: Decimal | None = None  # None: no limit on one side alone.
    max_leverage: Decimal
    daily_loss: Decimal
    daily_profit_stop: Decimal | None
    loss_stop: Decimal | None
    loss_stop_from_high: bool


class ArmingUpdate(BaseModel):
    """Real trading on or off from the dashboard (D063). Turning it on needs the password."""

    model_config = {"extra": "forbid"}

    armed: bool
    password: str | None = Field(default=None, max_length=256)


class ArmingView(BaseModel):
    armed: bool
    armed_at: UtcDatetime | None = None
