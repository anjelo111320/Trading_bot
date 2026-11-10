"""4H gap and 15M CHoCH strategy, version 1. Pre-registered in docs/35-FVG-CHOCH-STRATEGY.md.

Hypothesis, stated before any test: with the 4H trend agreeing, a 15M CHoCH that starts inside
an open 4H fair value gap and leaves a 15M gap behind starts a move that pays for a 2:1 trade
after costs, entering on the return to that 15M gap. This is an idea to test, not a claim that
it works.
"""

from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Any, Final

import numpy as np

from trading_intel.domain.candles import ClosedCandle, Timeframe
from trading_intel.domain.patterns import DetectedPattern, Direction
from trading_intel.domain.signals import Action, EntryType, Side
from trading_intel.market_structure.structure import StructureEvent, Trend, analyse_structure
from trading_intel.market_structure.swings import find_swings
from trading_intel.pattern_detection.imbalance import gap_at
from trading_intel.risk_management.models import TradeProposal
from trading_intel.technical_analysis.series import CandleSeries
from trading_intel.technical_analysis.volatility import atr
from trading_intel.trade_signals.baseline import BaselineDecision
from trading_intel.trade_signals.catalogue import (
    LevelCatalogue,
    build_catalogue,
    targets_beyond,
    to_tick,
)
from trading_intel.trade_signals.pattern_strategy import CATALOGUE_LOOKBACK, TrendView

STRATEGY_NAME: Final = "fvg_choch"
STRATEGY_VERSION: Final = 1
SETUP_TIMEFRAME: Final = Timeframe.M15
GAP_AGE: Final = timedelta(days=30)  # How old a 4H gap may be at the decision.


@dataclass(frozen=True)
class FvgChochParameters:
    """Every value was fixed before the first run. Changing one makes a new trial."""

    stop_buffer_atr: float = 0.25  # Beyond the pullback's extreme, where sweeps reach.
    min_target_r: float = 2.0  # The same rule as the other strategies.
    expiry_candles: int = 8  # Two hours for the limit to fill.
    leverage: str = "1"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Gap:
    direction: Direction
    low: float
    high: float
    formed_at: datetime  # The middle candle's close.
    detected_at: datetime  # The third candle's close.

    def pattern(self, timeframe: Timeframe) -> DetectedPattern:
        return DetectedPattern(
            pattern_type="fair_value_gap",
            direction=self.direction,
            formed_at=self.formed_at,
            detected_at=self.detected_at,
            zone_low=self.low,
            zone_high=self.high,
            evidence={"timeframe": timeframe.value},
        )


def _gap(series: CandleSeries, third: int) -> Gap | None:
    found = gap_at(series, third)
    if found is None:
        return None
    times = series.close_time
    return Gap(*found, formed_at=times[third - 1], detected_at=times[third])


def _round_away(value: Decimal, tick: Decimal, side: Side) -> Decimal:
    rounding = ROUND_FLOOR if side is Side.LONG else ROUND_CEILING
    return (value / tick).to_integral_value(rounding=rounding) * tick


def _no_trade(moment: datetime, reason: str, *patterns: DetectedPattern) -> BaselineDecision:
    return BaselineDecision(Action.NO_TRADE, moment, (reason,), patterns=patterns)


class FvgChochStrategy:
    """Structure, gaps, trend and ATR are computed once over the candles given.

    Each is prefix-stable: a gap needs only its three candles, a swing is used only after its
    confirmation, and fills are checked only up to the decision. Reading them at a candle gives
    what a live run would have known then. Each decision is kept, so repeated runs agree.
    """

    timeframe: Final = SETUP_TIMEFRAME

    def __init__(
        self,
        setup: Sequence[ClosedCandle],
        four_hours: Sequence[ClosedCandle],
        tick: Decimal,
        parameters: FvgChochParameters | None = None,
    ) -> None:
        self.parameters = parameters or FvgChochParameters()
        self.series = CandleSeries.of(setup)
        self.tick = tick
        self.atr = atr(self.series)
        self.index_of = {moment: i for i, moment in enumerate(self.series.close_time)}
        structure = analyse_structure(self.series, find_swings(self.series))
        self.changes: dict[int, StructureEvent] = {
            event.index: event for event in structure.events if event.kind == "CHOCH"
        }
        self.bias = TrendView(four_hours)
        fours = CandleSeries.of(four_hours)
        self.higher_gaps = [g for i in range(2, len(fours)) if (g := _gap(fours, i)) is not None]
        self._gap_times = [gap.detected_at for gap in self.higher_gaps]
        self._decided: dict[datetime, BaselineDecision] = {}

    def trends_at(self, moment: datetime) -> tuple[Trend, Trend]:
        """The 4H trend twice, so the random benchmark's agreement check reads the one trend."""
        trend = self.bias.at(moment)
        return trend, trend

    def decide(self, moment: datetime) -> BaselineDecision:
        """Decide using only what was known when the 15M candle closed at `moment`."""
        decision = self._decided.get(moment)
        if decision is None:
            decision = self._decided[moment] = self._decide(moment)
        return decision

    def _decide(self, moment: datetime) -> BaselineDecision:
        index = self.index_of.get(moment)
        if index is None:
            return _no_trade(moment, "no setup candle closed")
        event = self.changes.get(index)
        if event is None:
            return _no_trade(moment, "no CHoCH on this 15M candle")
        change = DetectedPattern(
            pattern_type="choch",
            direction=event.direction,
            formed_at=self.series.close_time[event.swing_index],
            detected_at=moment,
            price_level=event.level,
            evidence={"timeframe": SETUP_TIMEFRAME.value},
        )
        long = event.direction is Direction.BULLISH
        wanted: Trend = "up" if long else "down"
        bias = self.bias.at(moment)
        if bias != wanted:
            return _no_trade(moment, f"CHoCH against the 4H trend: 4H {bias}", change)
        extreme_index = self._extreme(event.swing_index, index, long)
        extreme = float((self.series.low if long else self.series.high)[extreme_index])
        zone = self._higher_gap(extreme_index, index, extreme, event.direction)
        if zone is None:
            return _no_trade(moment, "the pullback did not reach an open 4H gap", change)
        patterns: tuple[DetectedPattern, ...] = (zone.pattern(Timeframe.H4), change)
        entry_gap = self._entry_gap(extreme_index, index, event.direction)
        if entry_gap is None:
            return _no_trade(moment, "no open 15M gap in the move", *patterns)
        patterns = (*patterns, entry_gap.pattern(SETUP_TIMEFRAME))
        near = entry_gap.high if long else entry_gap.low
        close = float(self.series.close[index])
        if (close - near) * (1 if long else -1) <= 0:
            return _no_trade(moment, "price is back inside the 15M gap", *patterns)
        catalogue = self._catalogue_at(index)
        if catalogue is None:
            return _no_trade(moment, "volatility is still warming up", *patterns)
        side = Side.LONG if long else Side.SHORT
        return self._propose(moment, side, near, extreme, catalogue, zone, patterns)

    def _extreme(self, start: int, end: int, long: bool) -> int:
        """The pullback's lowest low for a long, or highest high for a short."""
        values = (self.series.low if long else self.series.high)[start : end + 1]
        return start + int(np.argmin(values) if long else np.argmax(values))

    def _filled(self, gap: Gap, start: int, end: int) -> bool:
        """Whether any candle from `start` to `end` reached the gap's far edge."""
        if start > end:
            return False
        if gap.direction is Direction.BULLISH:
            return bool(np.min(self.series.low[start : end + 1]) <= gap.low)
        return bool(np.max(self.series.high[start : end + 1]) >= gap.high)

    def _higher_gap(
        self, extreme_index: int, index: int, extreme: float, direction: Direction
    ) -> Gap | None:
        """The most recent open 4H gap in the trade's direction that holds the pullback."""
        moment = self.series.close_time[index]
        first = bisect_left(self._gap_times, moment - GAP_AGE)
        last = bisect_right(self._gap_times, self.series.open_time[extreme_index])
        for gap in reversed(self.higher_gaps[first:last]):
            if gap.direction is not direction:
                continue
            bullish = direction is Direction.BULLISH
            inside = gap.low < extreme <= gap.high if bullish else gap.low <= extreme < gap.high
            since = bisect_left(self.series.open_time, gap.detected_at)
            if inside and not self._filled(gap, since, index):
                return gap
        return None

    def _entry_gap(self, extreme_index: int, index: int, direction: Direction) -> Gap | None:
        """The most recent open 15M gap whose first candle is at or after the extreme."""
        for third in range(index, extreme_index + 1, -1):
            gap = _gap(self.series, third)
            if gap is None or gap.direction is not direction:
                continue
            if not self._filled(gap, third + 1, index):
                return gap
        return None

    def _catalogue_at(self, index: int) -> LevelCatalogue | None:
        start = index - CATALOGUE_LOOKBACK + 1
        window = self.series.window(start, index + 1)
        return build_catalogue(
            window, find_swings(window), self.atr[max(start, 0) : index + 1], self.tick
        )

    def _propose(
        self,
        moment: datetime,
        side: Side,
        near: float,
        extreme: float,
        catalogue: LevelCatalogue,
        zone: Gap,
        patterns: tuple[DetectedPattern, ...],
    ) -> BaselineDecision:
        params, tick = self.parameters, self.tick
        entry = to_tick(near, tick)
        buffer = Decimal(str(params.stop_buffer_atr)) * catalogue.atr
        stop = _round_away(Decimal(str(extreme)) - side.sign * buffer, tick, side)
        risk = side.sign * (entry - stop)
        if risk <= 0 or stop <= 0:
            return _no_trade(moment, "the stop is out of range", *patterns)
        targets = targets_beyond(catalogue, side, entry, risk, Decimal(str(params.min_target_r)))
        if not targets:
            return _no_trade(moment, "no reachable target", *patterns)
        long = side is Side.LONG
        condition = "close below" if long else "close above"
        trend = "up" if long else "down"
        edges = f"{to_tick(zone.low, tick)} to {to_tick(zone.high, tick)}"
        return BaselineDecision(
            action=Action.BUY if long else Action.SELL,
            as_of=moment,
            reasons=(
                f"15M CHoCH from inside the 4H gap {edges}, limit at the 15M gap, 4H {trend}",
            ),
            proposal=TradeProposal(
                side=side,
                entry_type=EntryType.LIMIT,
                entry=entry,
                stop=stop,
                targets=targets,
                leverage=Decimal(params.leverage),
                expiry_candles=params.expiry_candles,
                invalidation_conditions=(f"{condition} {stop}",),
            ),
            catalogue=catalogue,
            setup_atr=catalogue.atr,
            patterns=patterns,
        )
