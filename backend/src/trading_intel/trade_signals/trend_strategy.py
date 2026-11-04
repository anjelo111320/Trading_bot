"""Daily trend following, version 1. Pre-registered in docs/29-TREND-STRATEGY.md.

Hypothesis, stated before any test: on BTC and ETH perpetuals, a daily close beyond the
prior 20-day range starts moves that a 10-day trailing exit captures well enough to pay
for 2 ATR stops and costs. The rules are the Turtle traders' System 1, unchanged. This is
an idea to test, not a claim that it works.
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

STRATEGY_NAME: Final = "daily_trend"
STRATEGY_VERSION: Final = 1


@dataclass(frozen=True)
class TrendParameters:
    """Turtle System 1 values, fixed before the first run."""

    entry_days: int = 20
    exit_days: int = 10
    atr_days: int = 20
    stop_atr: float = 2.0
    # A far profit cap, so the 2:1 rule can read the trade. Exits come from the trailing stop.
    profit_cap_r: float = 10.0
    leverage: str = "1"
    expiry_candles: int = 1

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _round_away(value: Decimal, tick: Decimal, side: Side) -> Decimal:
    rounding = ROUND_FLOOR if side is Side.LONG else ROUND_CEILING
    return (value / tick).to_integral_value(rounding=rounding) * tick


class DailyTrendStrategy:
    """Decides at each daily close and trails its stop at later daily closes."""

    timeframe: Final = Timeframe.D1

    def __init__(
        self,
        days: Sequence[ClosedCandle],
        tick: Decimal,
        parameters: TrendParameters | None = None,
    ) -> None:
        self.parameters = parameters or TrendParameters()
        self.series = CandleSeries.of(days)
        self.tick = tick
        self.atr = atr(self.series, self.parameters.atr_days)
        self.index_of = {moment: i for i, moment in enumerate(self.series.close_time)}

    def _breakout(self, index: int) -> Side | None:
        days = self.parameters.entry_days
        if index < days:
            return None
        window = slice(index - days, index)
        close = float(self.series.close[index])
        if close > float(self.series.high[window].max()):
            return Side.LONG
        if close < float(self.series.low[window].min()):
            return Side.SHORT
        return None

    def decide(self, moment: datetime) -> BaselineDecision:
        index = self.index_of.get(moment)
        side = None if index is None else self._breakout(index)
        if index is None or side is None:
            return BaselineDecision(Action.NO_TRADE, moment, ("no 20-day breakout",))
        return self.propose(
            index, moment, side, f"close beyond the {self.parameters.entry_days}-day range"
        )

    def propose(self, index: int, moment: datetime, side: Side, reason: str) -> BaselineDecision:
        params, tick = self.parameters, self.tick
        unit = float(self.atr[index])
        if unit != unit or unit <= 0:
            return BaselineDecision(Action.NO_TRADE, moment, ("volatility is still warming up",))
        entry = to_tick(float(self.series.close[index]), tick)
        stop = _round_away(entry - side.sign * Decimal(str(params.stop_atr * unit)), tick, side)
        risk = side.sign * (entry - stop)
        if risk <= 0 or stop <= 0:
            return BaselineDecision(Action.NO_TRADE, moment, ("stop is out of range",))
        cap = to_tick(entry + side.sign * Decimal(str(params.profit_cap_r)) * risk, tick)
        return BaselineDecision(
            action=Action.BUY if side is Side.LONG else Action.SELL,
            as_of=moment,
            reasons=(reason,),
            proposal=TradeProposal(
                side=side,
                entry_type=EntryType.MARKET,
                entry=entry,
                stop=stop,
                targets=(cap,),
                leverage=Decimal(params.leverage),
                expiry_candles=params.expiry_candles,
                invalidation_conditions=(f"{params.exit_days}-day trailing exit",),
            ),
            setup_atr=Decimal(str(unit)),
        )

    def trailing_stop(self, moment: datetime, side: Side, stop: Decimal) -> Decimal | None:
        """The 10-day extreme against the trade, if it is tighter than the current stop."""
        index = self.index_of.get(moment)
        if index is None:
            return None
        window = slice(max(index - self.parameters.exit_days + 1, 0), index + 1)
        extreme = (
            self.series.low[window].min() if side is Side.LONG else self.series.high[window].max()
        )
        level = to_tick(float(extreme), self.tick)
        return level if side.sign * (level - stop) > 0 else None
