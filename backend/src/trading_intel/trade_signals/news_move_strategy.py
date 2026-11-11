"""The news move strategy, version 1. Pre-registered in docs/40-NEWS-MOVE-STRATEGY.md (D056).

Hypothesis, stated before any test: a strong 1H move that the coin's news agrees with continues
far enough to pay for a 1.5 ATR stop and costs. This is an idea to test, not a claim that it
works.

This module holds the price rules only: a strong move with a strong close. The news check is
made by the signal service, which asks the injected news reading whether it agrees, so this
module never reads news and a move without agreeing news never trades.
"""

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Any, Final

from trading_intel.domain.candles import ClosedCandle, Timeframe
from trading_intel.domain.signals import Action, EntryType, Side
from trading_intel.risk_management.models import TradeProposal
from trading_intel.technical_analysis.series import CandleSeries
from trading_intel.technical_analysis.volatility import atr
from trading_intel.trade_signals.baseline import BaselineDecision
from trading_intel.trade_signals.catalogue import to_tick

STRATEGY_NAME: Final = "news_move"
STRATEGY_VERSION: Final = 1


@dataclass(frozen=True)
class NewsMoveParameters:
    """Fixed in docs/40 before the first run."""

    atr_hours: int = 14
    move_atr: float = 1.5  # The 1H body must be at least this many ATRs.
    strong_close: float = 0.7  # Close in the outer 30% of the candle's range.
    stop_atr: float = 1.5
    targets_r: tuple[float, ...] = (2.0, 3.0)
    leverage: str = "1"
    expiry_candles: int = 1

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _away(value: Decimal, tick: Decimal, side: Side) -> Decimal:
    """Round a stop away from the entry, so the risk is never smaller than planned."""
    rounding = ROUND_FLOOR if side is Side.LONG else ROUND_CEILING
    return (value / tick).to_integral_value(rounding=rounding) * tick


class NewsMoveStrategy:
    """Finds a strong 1H move. The service trades it only when the coin's news agrees."""

    timeframe: Final = Timeframe.H1

    def __init__(
        self,
        hours: Sequence[ClosedCandle],
        tick: Decimal,
        parameters: NewsMoveParameters | None = None,
    ) -> None:
        self.parameters = parameters or NewsMoveParameters()
        self.series = CandleSeries.of(hours)
        self.tick = tick
        self.atr = atr(self.series, self.parameters.atr_hours)
        self.index_of = {moment: i for i, moment in enumerate(self.series.close_time)}

    def _move(self, index: int) -> tuple[Side, float] | None:
        """The move's side and the ATR before it, if the candle is a strong move."""
        if index < 1:
            return None
        unit = float(self.atr[index - 1])
        if unit != unit or unit <= 0:
            return None
        series, params = self.series, self.parameters
        open_, close = float(series.open[index]), float(series.close[index])
        high, low = float(series.high[index]), float(series.low[index])
        span = high - low
        if span <= 0 or abs(close - open_) < params.move_atr * unit:
            return None
        side = Side.LONG if close > open_ else Side.SHORT
        placed = (close - low) / span if side is Side.LONG else (high - close) / span
        return (side, unit) if placed >= params.strong_close else None

    def decide(self, moment: datetime) -> BaselineDecision:
        index = self.index_of.get(moment)
        found = None if index is None else self._move(index)
        if index is None or found is None:
            return BaselineDecision(Action.NO_TRADE, moment, ("no strong 1H move",))
        side, unit = found
        params, tick = self.parameters, self.tick
        entry = to_tick(float(self.series.close[index]), tick)
        stop = _away(entry - side.sign * Decimal(str(params.stop_atr * unit)), tick, side)
        risk = side.sign * (entry - stop)
        if risk <= 0 or stop <= 0:
            return BaselineDecision(Action.NO_TRADE, moment, ("stop is out of range",))
        targets = tuple(
            max(to_tick(entry + side.sign * Decimal(str(r)) * risk, tick), tick)
            for r in params.targets_r
        )
        move = "up" if side is Side.LONG else "down"
        return BaselineDecision(
            action=Action.BUY if side is Side.LONG else Action.SELL,
            as_of=moment,
            reasons=(f"strong 1H move {move}, {params.move_atr} ATR or more, strong close",),
            proposal=TradeProposal(
                side=side,
                entry_type=EntryType.MARKET,
                entry=entry,
                stop=stop,
                targets=targets,
                leverage=Decimal(params.leverage),
                expiry_candles=params.expiry_candles,
                invalidation_conditions=(f"stop {params.stop_atr} ATR beyond the close",),
            ),
            setup_atr=Decimal(str(unit)),
        )
