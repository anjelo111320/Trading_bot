"""Daily trend following, version 1. Pre-registered in docs/29-TREND-STRATEGY.md.

Hypothesis, stated before any test: on BTC and ETH perpetuals, a daily close beyond the
prior 20-day range starts moves that a 10-day trailing exit captures well enough to pay
for 2 ATR stops and costs. The rules are the Turtle traders' System 1, unchanged. This is
an idea to test, not a claim that it works.
"""

from bisect import bisect_left
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


def _proposal(
    close: float,
    unit: float,
    side: Side,
    moment: datetime,
    reason: str,
    params: TrendParameters,
    tick: Decimal,
) -> BaselineDecision:
    """A market entry at `close`, its stop 2 ATR away and the far profit cap. Both versions."""
    if unit != unit or unit <= 0:
        return BaselineDecision(Action.NO_TRADE, moment, ("volatility is still warming up",))
    entry = to_tick(close, tick)
    stop = _round_away(entry - side.sign * Decimal(str(params.stop_atr * unit)), tick, side)
    risk = side.sign * (entry - stop)
    if risk <= 0 or stop <= 0:
        return BaselineDecision(Action.NO_TRADE, moment, ("stop is out of range",))
    cap = to_tick(entry + side.sign * Decimal(str(params.profit_cap_r)) * risk, tick)
    # A short's 10R can reach past zero on a cheap, volatile coin. Price cannot, so the cap
    # stops at the lowest price instead. It is far away either way, and exits still come
    # from the trailing stop (found on DOGE-like prices on 2026-11-07).
    cap = max(cap, tick)
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
        close = float(self.series.close[index])
        return _proposal(
            close, float(self.atr[index]), side, moment, reason, self.parameters, self.tick
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


INTRADAY_VERSION: Final = 2


class IntradayTrendStrategy:
    """Version 2 (docs/41): the same 20-day breakout, checked at each 1H close.

    The range is the 20 complete days before the current UTC day, so the day's own candle never
    counts. Only the first 1H close of the day beyond the range signals, so a breakout stopped
    out the same day does not re-enter. Stop, cap and the trailing exit are version 1's.
    """

    timeframe: Final = Timeframe.H1

    def __init__(
        self,
        hours: Sequence[ClosedCandle],
        days: Sequence[ClosedCandle],
        tick: Decimal,
        parameters: TrendParameters | None = None,
    ) -> None:
        self.daily = DailyTrendStrategy(days, tick, parameters)
        self.parameters = self.daily.parameters
        self.hours = CandleSeries.of(hours)
        self.tick = tick
        self.hour_index = {moment: i for i, moment in enumerate(self.hours.close_time)}
        self.day_closes = list(self.daily.series.close_time)

    def _range(self, moment: datetime) -> tuple[int, float, float] | None:
        """The last complete day's index, and the high and low of the 20 days ending there."""
        last = bisect_left(self.day_closes, Timeframe.D1.floor(moment)) - 1
        days = self.parameters.entry_days
        if last < days - 1:
            return None
        window = slice(last - days + 1, last + 1)
        series = self.daily.series
        return last, float(series.high[window].max()), float(series.low[window].min())

    def decide(self, moment: datetime) -> BaselineDecision:
        index = self.hour_index.get(moment)
        found = None if index is None else self._range(moment)
        if index is None or found is None:
            return BaselineDecision(Action.NO_TRADE, moment, ("no 20-day breakout",))
        last, high, low = found
        close = float(self.hours.close[index])
        side = Side.LONG if close > high else Side.SHORT if close < low else None
        if side is None:
            return BaselineDecision(Action.NO_TRADE, moment, ("no 20-day breakout",))
        day_start = Timeframe.D1.floor(moment)
        earlier = index - 1
        while earlier >= 0 and self.hours.close_time[earlier] > day_start:
            before = float(self.hours.close[earlier])
            if (before > high) if side is Side.LONG else (before < low):
                return BaselineDecision(
                    Action.NO_TRADE, moment, ("breakout already signalled today",)
                )
            earlier -= 1
        reason = f"1H close beyond the {self.parameters.entry_days}-day range"
        return _proposal(
            close, float(self.daily.atr[last]), side, moment, reason, self.parameters, self.tick
        )

    def trailing_stop(self, moment: datetime, side: Side, stop: Decimal) -> Decimal | None:
        """Version 1's 10-day trail, at daily closes only."""
        return self.daily.trailing_stop(moment, side, stop)
