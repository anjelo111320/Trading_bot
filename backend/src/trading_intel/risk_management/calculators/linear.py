"""Spot and USDT-margined linear perpetuals. Symbols follow docs/08-RISK-MANAGEMENT.md.

Both have a multiplier of 1 for the instruments in use, and profit linear in price. Spot has
no funding and no leverage. Inverse contracts, forex and equities do not fit this formula.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal

from trading_intel.domain.instruments import Instrument, InstrumentRules, InstrumentType
from trading_intel.domain.signals import EntryType
from trading_intel.risk_management.models import (
    AccountState,
    FeeRates,
    MarketState,
    RiskProfile,
    Sizing,
    TradeProposal,
)

ZERO = Decimal(0)
SUPPORTED = (InstrumentType.SPOT, InstrumentType.LINEAR_PERPETUAL)


def floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    """Round down to a multiple of the step, so actual risk never exceeds the budget."""
    return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


def remaining_daily_budget(account: AccountState, profile: RiskProfile) -> Decimal:
    limit = account.day_start_equity * profile.max_daily_loss_fraction
    loss = account.day_start_equity - account.equity
    return limit - loss


def scaled_allocation(allocation: Sequence[Decimal], count: int) -> tuple[Decimal, ...]:
    """Fewer targets rescale the shares. A missing target stays missing."""
    shares = allocation[:count]
    total = sum(shares, ZERO)
    return tuple(share / total for share in shares)


@dataclass(frozen=True)
class Fills:
    entry: Decimal
    stop: Decimal


def estimate_fills(proposal: TradeProposal, market: MarketState) -> Fills:
    """E and S. A limit entry pays no spread or slippage on the way in."""
    sign = proposal.side.sign
    half_spread = (market.ask - market.bid) / 2
    is_limit = proposal.entry_type is EntryType.LIMIT
    entry_cost = ZERO if is_limit else half_spread + market.entry_slippage
    return Fills(
        entry=proposal.entry + sign * entry_cost,
        stop=proposal.stop - sign * (half_spread + market.stop_slippage),
    )


def liquidation_price(entry: Decimal, proposal: TradeProposal, maintenance: Decimal) -> Decimal:
    """Approximate, because exact brackets need an API key the project does not hold."""
    inverse = Decimal(1) / proposal.leverage
    if proposal.side.sign > 0:
        return entry * (1 - inverse + maintenance)
    return entry * (1 + inverse - maintenance)


def size_trade(
    proposal: TradeProposal,
    account: AccountState,
    market: MarketState,
    instrument: Instrument,
    rules: InstrumentRules,
    fees: FeeRates,
    profile: RiskProfile,
) -> Sizing:
    sign = proposal.side.sign
    multiplier = instrument.contract_multiplier
    fills = estimate_fills(proposal, market)
    entry, stop = fills.entry, fills.stop

    entry_fee = fees.entry * entry * multiplier
    stop_fee = fees.exit * stop * multiplier
    perpetual = instrument.instrument_type is InstrumentType.LINEAR_PERPETUAL
    funding = (
        abs(market.funding_rate) * stop * multiplier * market.funding_intervals
        if perpetual
        else ZERO
    )
    risk_per_unit = sign * (entry - stop) * multiplier + entry_fee + stop_fee + funding

    budget = min(
        account.equity * profile.max_risk_fraction, remaining_daily_budget(account, profile)
    )
    usable = risk_per_unit > 0 and budget > 0
    quantity = floor_to_step(budget / risk_per_unit, rules.lot_step) if usable else ZERO

    wins = [
        sign * (target - entry) * multiplier - entry_fee - fees.exit * target * multiplier - funding
        for target in proposal.targets
    ]
    ratios = tuple(win / risk_per_unit for win in wins) if risk_per_unit > 0 else ()
    allocation = scaled_allocation(profile.target_allocation, len(proposal.targets))
    weighted = sum((share * ratio for share, ratio in zip(allocation, ratios, strict=False)), ZERO)
    notional = quantity * entry * multiplier
    leverage = proposal.leverage if perpetual else Decimal(1)
    liquidation = None
    if perpetual and rules.maintenance_margin_fraction is not None:
        liquidation = liquidation_price(entry, proposal, rules.maintenance_margin_fraction)
    return Sizing(
        entry_fill=entry,
        stop_fill=stop,
        entry_fee=entry_fee,
        stop_fee=stop_fee,
        funding=funding,
        risk_per_unit=risk_per_unit,
        risk_budget=budget,
        quantity=quantity,
        max_account_risk=quantity * risk_per_unit,
        notional=notional,
        margin=notional / leverage,
        liquidation_price=liquidation,
        target_reward_risk=ratios,
        weighted_reward_risk=weighted,
        allocation=allocation,
    )
