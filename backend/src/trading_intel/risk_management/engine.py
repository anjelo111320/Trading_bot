"""The risk engine. Pure and deterministic, and the same code runs live, in paper and in backtests.

Inputs are never adjusted: an invalid stop is refused, not moved. All failures are collected,
so a rejection explains itself completely.
"""

from collections.abc import Mapping
from decimal import Decimal
from itertools import pairwise
from typing import Any

from pydantic import ValidationError

from trading_intel.domain.instruments import InstrumentRules, InstrumentType
from trading_intel.domain.signals import EntryType
from trading_intel.risk_management.calculators.linear import (
    SUPPORTED,
    daily_profit_reached,
    remaining_daily_budget,
    remaining_open_risk,
    size_trade,
)
from trading_intel.risk_management.models import (
    MAX_EXPIRY_CANDLES,
    MarketState,
    RiskAssessment,
    RiskRequest,
    Sizing,
    TradeProposal,
)
from trading_intel.risk_management.rejections import RejectionCode as Code

TRADING_STATUS = "TRADING"
MARKET_ENTRY_TOLERANCE = Decimal("0.001")
BASIS_POINTS = Decimal(10_000)
ZERO = Decimal(0)


def _rejected(*codes: Code) -> RiskAssessment:
    return RiskAssessment(approved=False, codes=tuple(codes), sizing=None)


def assess_raw(payload: Mapping[str, Any]) -> RiskAssessment:
    """Validate untrusted input first. Anything malformed, or any float, is refused."""
    try:
        request = RiskRequest.model_validate(payload)
    except ValidationError:
        return _rejected(Code.SCHEMA_INVALID)
    return assess(request)


def assess(request: RiskRequest) -> RiskAssessment:
    if request.instrument.instrument_type not in SUPPORTED:
        return _rejected(Code.INSTRUMENT_NOT_SUPPORTED)
    missing = []
    if request.rules is None:
        missing.append(Code.INSTRUMENT_RULES_MISSING)
    if request.fees is None:
        missing.append(Code.FEE_SCHEDULE_MISSING)
    if missing or request.rules is None or request.fees is None:
        return _rejected(*missing)

    codes = [
        *_market_checks(request),
        *_level_checks(request.proposal, request.market),
        *_tick_checks(request.proposal, request.rules),
        *_policy_checks(request),
    ]
    sizing = None
    if request.proposal.entry > 0 and request.proposal.targets:
        sizing = size_trade(
            request.proposal,
            request.account,
            request.market,
            request.instrument,
            request.rules,
            request.fees,
            request.profile,
        )
        codes += _sizing_checks(request, request.rules, sizing)
    unique = tuple(dict.fromkeys(codes))
    return RiskAssessment(approved=not unique, codes=unique, sizing=sizing)


def _market_checks(request: RiskRequest) -> list[Code]:
    assert request.rules is not None
    market, profile = request.market, request.profile
    codes: list[Code] = []
    if request.rules.status != TRADING_STATUS:
        codes.append(Code.MARKET_NOT_TRADING)
    if market.data_age_seconds > profile.max_data_age_seconds:
        codes.append(Code.DATA_STALE)
    if market.has_open_gaps:
        codes.append(Code.DATA_INCOMPLETE)
    middle = (market.bid + market.ask) / 2
    if (market.ask - market.bid) / middle * BASIS_POINTS > profile.max_spread_bps:
        codes.append(Code.SPREAD_TOO_WIDE)
    return codes


def _entry_possible(proposal: TradeProposal, market: MarketState) -> bool:
    """A limit buy at or above the ask, for example, would not be a limit order."""
    long = proposal.side.sign > 0
    match proposal.entry_type:
        case EntryType.LIMIT:
            return proposal.entry < market.ask if long else proposal.entry > market.bid
        case EntryType.STOP:
            return proposal.entry > market.ask if long else proposal.entry < market.bid
        case EntryType.MARKET:
            middle = (market.bid + market.ask) / 2
            return abs(proposal.entry - middle) / middle <= MARKET_ENTRY_TOLERANCE
    return False


def _level_checks(proposal: TradeProposal, market: MarketState) -> list[Code]:
    codes: list[Code] = []
    sign = proposal.side.sign
    if proposal.entry <= 0 or not _entry_possible(proposal, market):
        codes.append(Code.INVALID_ENTRY)
    stop_ok = sign * (proposal.entry - proposal.stop) > 0 and proposal.stop > 0
    if not stop_ok:
        codes.append(Code.STOP_WRONG_SIDE)
    if not proposal.targets:
        codes.append(Code.NO_TARGET)
        return codes
    # A target at or below zero is on no side of a real market.
    wrong = [t for t in proposal.targets if t <= 0 or sign * (t - proposal.entry) <= 0]
    if wrong:
        codes.append(Code.TARGET_WRONG_SIDE)
    if not stop_ok and len(wrong) == len(proposal.targets):
        codes.append(Code.INVALID_DIRECTION)
    distances = [sign * (t - proposal.entry) for t in proposal.targets]
    if any(later <= earlier for earlier, later in pairwise(distances)):
        codes.append(Code.TARGET_ORDER_INVALID)
    return codes


def _tick_checks(proposal: TradeProposal, rules: InstrumentRules) -> list[Code]:
    prices = (proposal.entry, proposal.stop, *proposal.targets)
    if any(price % rules.tick_size != 0 for price in prices):
        return [Code.NOT_TICK_ALIGNED]
    return []


def _policy_checks(request: RiskRequest) -> list[Code]:
    proposal, account, profile = request.proposal, request.account, request.profile
    codes: list[Code] = []
    if remaining_daily_budget(account, profile) <= 0:
        codes.append(Code.DAILY_LOSS_REACHED)
    if daily_profit_reached(account, profile):
        codes.append(Code.DAILY_PROFIT_REACHED)
    room = remaining_open_risk(account, profile)
    if room is not None and room <= 0:
        codes.append(Code.OPEN_RISK_FULL)
    if account.open_positions >= profile.max_open_positions:
        codes.append(Code.MAX_OPEN_POSITIONS)
    is_spot = request.instrument.instrument_type is InstrumentType.SPOT
    if proposal.leverage > (Decimal(1) if is_spot else profile.max_leverage):
        codes.append(Code.LEVERAGE_EXCEEDED)
    if request.duplicate_active:
        codes.append(Code.DUPLICATE_ACTIVE_SIGNAL)
    expiry = proposal.expiry_candles
    if expiry is None or not 0 < expiry <= MAX_EXPIRY_CANDLES:
        codes.append(Code.EXPIRY_INVALID)
    if not proposal.invalidation_conditions:
        codes.append(Code.INVALIDATION_MISSING)
    return codes


def _sizing_checks(request: RiskRequest, rules: InstrumentRules, sizing: Sizing) -> list[Code]:
    proposal, account, profile = request.proposal, request.account, request.profile
    codes: list[Code] = []
    minimum = profile.min_reward_risk
    if proposal.is_countertrend:
        minimum += profile.countertrend_extra_rr
    if sizing.risk_per_unit > 0 and sizing.target_reward_risk:
        if sizing.weighted_reward_risk < minimum:
            codes.append(Code.RR_BELOW_MIN)
        if sizing.target_reward_risk[0] <= 0:
            codes.append(Code.TP1_NOT_PROFITABLE)
    if sizing.quantity < rules.min_qty or sizing.quantity <= 0:
        codes.append(Code.QTY_BELOW_MIN)
    if sizing.quantity > rules.max_qty:
        codes.append(Code.QTY_ABOVE_MAX)
    if sizing.notional < rules.min_notional:
        codes.append(Code.NOTIONAL_BELOW_MIN)
    limit = account.equity * profile.max_total_exposure_fraction
    if account.gross_exposure + sizing.notional > limit:
        codes.append(Code.EXPOSURE_EXCEEDED)
    codes += _liquidation_checks(request, sizing)
    return codes


def _liquidation_checks(request: RiskRequest, sizing: Sizing) -> list[Code]:
    """The stop must fire well before liquidation could."""
    liquidation = sizing.liquidation_price
    atr = request.market.setup_atr
    if liquidation is None:
        return []
    room = request.proposal.side.sign * (request.proposal.stop - liquidation)
    if room < (atr if atr is not None else ZERO):
        return [Code.LIQUIDATION_INSIDE_STOP]
    return []
