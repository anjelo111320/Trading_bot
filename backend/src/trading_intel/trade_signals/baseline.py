"""The rule baseline: a deterministic strategy that can be backtested honestly.

Hypothesis, stated before any test: on the setup timeframe, a break of structure in the
direction of both higher timeframes, in a directional market, travels far enough to pay
for itself after costs. This is an idea to test, not a claim that it works.
"""

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Any, Final

import numpy as np

from trading_intel.domain.candles import Timeframe
from trading_intel.domain.patterns import DetectedPattern, Direction
from trading_intel.domain.signals import Action, EntryType, Side
from trading_intel.market_structure.structure import Trend, analyse_structure
from trading_intel.market_structure.swings import find_swings
from trading_intel.risk_management.models import TradeProposal
from trading_intel.technical_analysis.series import CandleSeries, FloatArray
from trading_intel.technical_analysis.trend import adx
from trading_intel.technical_analysis.volatility import atr
from trading_intel.trade_signals.catalogue import LevelCatalogue, build_catalogue, targets_beyond

STRATEGY_NAME: Final = "trend_break_baseline"
STRATEGY_VERSION: Final = 2  # Version 1 picked targets that could not pass the 2:1 rule.
SETUP_TIMEFRAME: Final = Timeframe.M15
SWING_BUFFER_ATR: Final = "0.25"


@dataclass(frozen=True)
class BaselineParameters:
    """Few parameters, each with a reason. Every trial is recorded with these values."""

    min_adx: float = 20.0  # Below this, ADX reads as no directional market.
    stop_buffer_atr: float = 0.25  # Stops sit beyond the swing, where sweeps tend to reach.
    min_target_r: float = 2.0  # The first target must clear the 2:1 rule on its own.
    expiry_candles: int = 8
    leverage: str = "1"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BaselineDecision:
    action: Action
    as_of: datetime
    reasons: tuple[str, ...]
    proposal: TradeProposal | None = None
    catalogue: LevelCatalogue | None = None
    setup_atr: Decimal | None = None
    patterns: tuple[DetectedPattern, ...] = ()  # What triggered it, for reports and Claude.


def _no_trade(as_of: datetime, *reasons: str) -> BaselineDecision:
    return BaselineDecision(Action.NO_TRADE, as_of, reasons)


def _trend_of(series: CandleSeries) -> Trend:
    return analyse_structure(series, find_swings(series)).trend[-1]


def _stop_below_swing(series_low: Decimal, buffer: Decimal, tick: Decimal, side: Side) -> Decimal:
    raw = series_low - side.sign * buffer
    rounding = ROUND_FLOOR if side is Side.LONG else ROUND_CEILING
    return (raw / tick).to_integral_value(rounding=rounding) * tick


def evaluate(
    setup: CandleSeries,
    middle: CandleSeries,
    higher: CandleSeries,
    tick: Decimal,
    parameters: BaselineParameters | None = None,
) -> BaselineDecision:
    """Decide using only the candles supplied, all of which must already be closed."""
    params = parameters or BaselineParameters()
    as_of = setup.close_time[-1]
    swings = find_swings(setup)
    structure = analyse_structure(setup, swings)
    last = len(setup) - 1
    breaks = [e for e in structure.events if e.index == last]
    if not breaks:
        return _no_trade(as_of, "no break of structure on the latest candle")
    event = breaks[-1]
    side = Side.LONG if event.direction is Direction.BULLISH else Side.SHORT
    wanted: Trend = "up" if side is Side.LONG else "down"
    if _trend_of(higher) != wanted or _trend_of(middle) != wanted:
        return _no_trade(as_of, "higher timeframes do not agree")

    strength: FloatArray = adx(setup).adx
    if np.isnan(strength[last]) or float(strength[last]) < params.min_adx:
        return _no_trade(as_of, "market is not directional enough")

    volatility = atr(setup)
    catalogue = build_catalogue(setup, swings, volatility, tick)
    if catalogue is None:
        return _no_trade(as_of, "volatility is still warming up")
    kind = "low" if side is Side.LONG else "high"
    opposite = [s for s in swings if s.kind == kind and s.confirmed_index <= last]
    if not opposite:
        return _no_trade(as_of, "no confirmed swing to place a stop behind")

    entry = catalogue.close
    buffer = Decimal(str(params.stop_buffer_atr)) * catalogue.atr
    stop = _stop_below_swing(Decimal(str(opposite[-1].price)), buffer, tick, side)
    risk = side.sign * (entry - stop)
    if risk <= 0:
        return _no_trade(as_of, "latest swing is on the wrong side of the close")
    targets = targets_beyond(catalogue, side, entry, risk, Decimal(str(params.min_target_r)))
    if not targets:
        return _no_trade(as_of, "no reachable target")
    condition = "close below" if side is Side.LONG else "close above"
    return BaselineDecision(
        action=Action.BUY if side is Side.LONG else Action.SELL,
        as_of=as_of,
        reasons=(f"{event.kind} with both higher timeframes {wanted}",),
        proposal=TradeProposal(
            side=side,
            entry_type=EntryType.MARKET,
            entry=entry,
            stop=stop,
            targets=targets,
            leverage=Decimal(params.leverage),
            expiry_candles=params.expiry_candles,
            invalidation_conditions=(f"{condition} {stop}",),
        ),
        catalogue=catalogue,
        setup_atr=catalogue.atr,
    )
