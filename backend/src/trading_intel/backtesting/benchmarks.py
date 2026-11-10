"""Benchmarks a strategy must beat, run through the same engine, costs and risk rules."""

import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Final, Protocol

from trading_intel.domain.candles import ClosedCandle, Timeframe
from trading_intel.domain.signals import Action, EntryType, Side
from trading_intel.market_structure.structure import Trend
from trading_intel.risk_management.models import TradeProposal
from trading_intel.technical_analysis.series import CandleSeries, FloatArray
from trading_intel.trade_signals.baseline import BaselineDecision
from trading_intel.trade_signals.catalogue import to_tick
from trading_intel.trade_signals.trend_strategy import DailyTrendStrategy, TrendParameters

ZERO: Final = Decimal(0)


class _Expiring(Protocol):
    @property
    def expiry_candles(self) -> int: ...


class TrendSetups(Protocol):
    """What the random benchmark reads from a strategy: its setup candles and trend filter."""

    series: CandleSeries
    atr: FloatArray
    tick: Decimal
    index_of: dict[datetime, int]

    @property
    def timeframe(self) -> Timeframe: ...

    @property
    def parameters(self) -> _Expiring: ...

    def trends_at(self, moment: datetime) -> tuple[Trend, Trend]: ...


@dataclass(frozen=True)
class ExitTemplate:
    """A real signal's stop distance in ATR and its targets in R."""

    stop_atr: float
    target_r: tuple[float, ...]


def exit_template(
    entry: Decimal, stop: Decimal, targets: Sequence[Decimal], atr: Decimal
) -> ExitTemplate:
    risk = abs(entry - stop)
    return ExitTemplate(
        stop_atr=float(risk / atr),
        target_r=tuple(float(abs(target - entry) / risk) for target in targets),
    )


class RandomTrendEntries:
    """Random setup candles where 4H and 1D agree, traded in that direction.

    Exits copy the shape of real signals, so only the timing differs from the strategy under
    test. A strategy that cannot beat this has shown no value beyond the trend filter.
    """

    def __init__(
        self,
        base: TrendSetups,
        templates: Sequence[ExitTemplate],
        count: int,
        seed: int,
        start: datetime,
        end: datetime,
    ) -> None:
        if not templates:
            raise ValueError("the benchmark needs at least one real signal to copy")
        self._base = base
        rng = random.Random(seed)  # noqa: S311 - a seeded benchmark, not security.
        series = base.series
        eligible = [
            moment
            for index, moment in enumerate(series.close_time)
            if start <= moment < end
            and base.atr[index] == base.atr[index]
            and self._side(moment) is not None
        ]
        chosen = sorted(rng.sample(eligible, min(count, len(eligible))))
        self._plan = {moment: rng.choice(list(templates)) for moment in chosen}

    @property
    def timeframe(self) -> Timeframe:
        return self._base.timeframe

    @property
    def planned(self) -> list[datetime]:
        return sorted(self._plan)

    def _side(self, moment: datetime) -> Side | None:
        middle, higher = self._base.trends_at(moment)
        if middle == higher == "up":
            return Side.LONG
        if middle == higher == "down":
            return Side.SHORT
        return None

    def decide(self, moment: datetime) -> BaselineDecision:
        template = self._plan.get(moment)
        side = self._side(moment)
        if template is None or side is None:
            return BaselineDecision(Action.NO_TRADE, moment, ("not a sampled candle",))
        index = self._base.index_of[moment]
        tick = self._base.tick
        unit = Decimal(str(float(self._base.atr[index])))
        entry = to_tick(float(self._base.series.close[index]), tick)
        distance = to_tick(Decimal(str(template.stop_atr)) * unit, tick)
        stop = entry - side.sign * max(distance, tick)
        risk = abs(entry - stop)
        targets = tuple(
            entry + side.sign * to_tick(Decimal(str(r)) * risk, tick) for r in template.target_r
        )
        if stop <= ZERO or any(t <= ZERO for t in targets):
            return BaselineDecision(Action.NO_TRADE, moment, ("prices out of range",))
        condition = "close below" if side is Side.LONG else "close above"
        return BaselineDecision(
            action=Action.BUY if side is Side.LONG else Action.SELL,
            as_of=moment,
            reasons=("random entry with the trend",),
            proposal=TradeProposal(
                side=side,
                entry_type=EntryType.MARKET,
                entry=entry,
                stop=stop,
                targets=targets,
                expiry_candles=self._base.parameters.expiry_candles,
                invalidation_conditions=(f"{condition} {stop}",),
            ),
            setup_atr=unit,
        )


class RandomDailyEntries(DailyTrendStrategy):
    """Benchmark for trend following: random days and directions, with the same stops and exit.

    If breakouts cannot beat entering at random with the same risk and trailing exit, the
    entry rule adds nothing.
    """

    def __init__(
        self,
        days: Sequence[ClosedCandle],
        tick: Decimal,
        parameters: TrendParameters,
        count: int,
        seed: int,
        window: tuple[datetime, datetime],
    ) -> None:
        super().__init__(days, tick, parameters)
        rng = random.Random(seed)  # noqa: S311 - a seeded benchmark, not security.
        eligible = [
            moment
            for index, moment in enumerate(self.series.close_time)
            if window[0] <= moment < window[1] and self.atr[index] == self.atr[index]
        ]
        chosen = sorted(rng.sample(eligible, min(count, len(eligible))))
        self._sides = {moment: rng.choice((Side.LONG, Side.SHORT)) for moment in chosen}

    def decide(self, moment: datetime) -> BaselineDecision:
        side = self._sides.get(moment)
        if side is None:
            return BaselineDecision(Action.NO_TRADE, moment, ("not a sampled day",))
        return self.propose(self.index_of[moment], moment, side, "random entry")
