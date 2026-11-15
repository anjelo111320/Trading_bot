"""Inputs and outputs of the engine. Strict Decimal, so a float is refused at the boundary."""

from decimal import Decimal
from typing import Final

from pydantic import Field, model_validator

from trading_intel.domain.base import DomainModel
from trading_intel.domain.instruments import Instrument, InstrumentRules
from trading_intel.domain.signals import EntryType, Side
from trading_intel.risk_management.rejections import RejectionCode

ENGINE_VERSION: Final = "1"
MAX_EXPIRY_CANDLES: Final = 24
DEFAULT_EXPIRY_CANDLES: Final = 8

# Ceilings the API cannot exceed, whatever a stored profile says. The per-trade and daily loss
# ceilings were raised from 2% and 5% to 10% by the owner's choice on 2026-11-12 (D058),
# after backtests nearly emptied the account at that level. Defaults stay at 1% and 3%.
CEILING_RISK_FRACTION: Final = Decimal("0.10")
FLOOR_REWARD_RISK: Final = Decimal(1)
CEILING_DAILY_LOSS: Final = Decimal("0.10")
CEILING_LEVERAGE: Final = Decimal(5)
CEILING_OPEN_RISK: Final = Decimal("0.1")
CEILING_EXPOSURE: Final = Decimal(5)


class RiskProfile(DomainModel):
    max_risk_fraction: Decimal = Decimal("0.01")
    min_reward_risk: Decimal = Decimal("2.0")
    max_daily_loss_fraction: Decimal = Decimal("0.03")
    max_open_positions: int = 3
    max_total_exposure_fraction: Decimal = Decimal("1.0")
    max_leverage: Decimal = Decimal(3)
    countertrend_extra_rr: Decimal = Decimal("0.5")
    max_spread_bps: Decimal = Decimal(5)
    max_data_age_seconds: int = 30
    target_allocation: tuple[Decimal, ...] = (Decimal("0.5"), Decimal("0.3"), Decimal("0.2"))
    # The money plan's limits (D045). None leaves an account as it was.
    max_open_risk_fraction: Decimal | None = None
    daily_profit_stop_fraction: Decimal | None = None
    # New trades stop for good once the account is this far below its starting balance (D053),
    # or below its highest equity when `loss_stop_from_high` is set (D058).
    max_total_loss_fraction: Decimal | None = None
    loss_stop_from_high: bool = False
    # No single position larger than this share of equity, so one trade never takes all the room
    # for positions (D061). None leaves only the limit on all positions together.
    max_position_fraction: Decimal | None = None
    # All positions and waiting entries on one side, long or short, at most this share of
    # equity, because the coins rise and fall together (D072). None leaves only the limit on
    # all positions together.
    max_side_exposure_fraction: Decimal | None = None

    @model_validator(mode="after")
    def _within_ceilings(self) -> RiskProfile:
        if not Decimal(0) < self.max_risk_fraction <= CEILING_RISK_FRACTION:
            raise ValueError("max_risk_fraction is outside its ceiling")
        if self.min_reward_risk < FLOOR_REWARD_RISK:
            raise ValueError("min_reward_risk is below its floor")
        if not Decimal(0) < self.max_daily_loss_fraction <= CEILING_DAILY_LOSS:
            raise ValueError("max_daily_loss_fraction is outside its ceiling")
        if not Decimal(1) <= self.max_leverage <= CEILING_LEVERAGE:
            raise ValueError("max_leverage is outside its ceiling")
        if not Decimal(0) < self.max_total_exposure_fraction <= CEILING_EXPOSURE:
            raise ValueError("max_total_exposure_fraction is outside its ceiling")
        if sum(self.target_allocation, Decimal(0)) != Decimal(1):
            raise ValueError("target_allocation must sum to 1")
        open_risk = self.max_open_risk_fraction
        if open_risk is not None and not self.max_risk_fraction <= open_risk <= CEILING_OPEN_RISK:
            raise ValueError("max_open_risk_fraction is outside its range")
        profit_stop = self.daily_profit_stop_fraction
        if profit_stop is not None and profit_stop <= 0:
            raise ValueError("daily_profit_stop_fraction must be positive")
        total_loss = self.max_total_loss_fraction
        if total_loss is not None and not Decimal(0) < total_loss < Decimal(1):
            raise ValueError("max_total_loss_fraction is outside its range")
        largest = self.max_position_fraction
        if largest is not None and not Decimal(0) < largest <= self.max_total_exposure_fraction:
            raise ValueError("max_position_fraction must be above 0 and within the position cap")
        side = self.max_side_exposure_fraction
        if side is not None and not Decimal(0) < side <= self.max_total_exposure_fraction:
            raise ValueError(
                "max_side_exposure_fraction must be above 0 and within the position cap"
            )
        return self


class FeeRates(DomainModel):
    entry: Decimal
    exit: Decimal


class AccountState(DomainModel):
    equity: Decimal = Field(gt=0)
    day_start_equity: Decimal = Field(gt=0)
    open_positions: int = Field(ge=0)
    gross_exposure: Decimal = Field(ge=0)
    # What open and pending positions would lose at their current stops.
    open_risk: Decimal = Field(default=Decimal(0), ge=0)
    # Margin the exchange can still lend this trade, for an account on Binance (D048). None for
    # paper accounts, which hold no margin.
    available_margin: Decimal | None = Field(default=None, ge=0)
    # The equity a loss stop is measured from (D053): the starting balance, or the highest
    # equity when the stop follows profits (D058). None leaves the stop off.
    start_equity: Decimal | None = Field(default=None, gt=0)
    # Positions and waiting entries on each side, for the limit on one direction (D072).
    long_exposure: Decimal = Field(default=Decimal(0), ge=0)
    short_exposure: Decimal = Field(default=Decimal(0), ge=0)


class MarketState(DomainModel):
    bid: Decimal = Field(gt=0)
    ask: Decimal = Field(gt=0)
    entry_slippage: Decimal = Field(ge=0)
    stop_slippage: Decimal = Field(ge=0)
    setup_atr: Decimal | None = None
    funding_rate: Decimal = Decimal(0)
    funding_intervals: int = Field(default=0, ge=0)
    data_age_seconds: int = Field(ge=0)
    has_open_gaps: bool = False


class TradeProposal(DomainModel):
    """The only way into the engine. Each number was resolved by Python, not by a model."""

    side: Side
    entry_type: EntryType
    entry: Decimal
    stop: Decimal
    targets: tuple[Decimal, ...]
    leverage: Decimal = Decimal(1)
    is_countertrend: bool = False
    expiry_candles: int | None = DEFAULT_EXPIRY_CANDLES
    invalidation_conditions: tuple[str, ...] = ()
    # The money plan's share of the profile's risk per trade (D045). It can only lower risk.
    risk_share: Decimal = Field(default=Decimal(1), gt=0, le=1)


class RiskRequest(DomainModel):
    proposal: TradeProposal
    account: AccountState
    market: MarketState
    instrument: Instrument
    rules: InstrumentRules | None
    fees: FeeRates | None
    profile: RiskProfile
    duplicate_active: bool = False


class Sizing(DomainModel):
    entry_fill: Decimal
    stop_fill: Decimal
    entry_fee: Decimal
    stop_fee: Decimal
    funding: Decimal
    risk_per_unit: Decimal
    risk_budget: Decimal
    quantity: Decimal
    max_account_risk: Decimal
    notional: Decimal
    margin: Decimal
    liquidation_price: Decimal | None
    target_reward_risk: tuple[Decimal, ...]
    weighted_reward_risk: Decimal
    allocation: tuple[Decimal, ...]


class RiskAssessment(DomainModel):
    approved: bool
    codes: tuple[RejectionCode, ...]
    sizing: Sizing | None
    engine_version: str = ENGINE_VERSION
