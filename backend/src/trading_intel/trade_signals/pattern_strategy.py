"""Pattern breakout strategy, version 1. Pre-registered in docs/27-PATTERN-SIGNAL-PLAN.md.

Hypothesis, stated before any test: a confirmed 1H chart-pattern breakout in the direction
of both the 4H and 1D swing trend travels far enough to pay for a 2:1 trade after costs.
This is an idea to test, not a claim that it works.
"""

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Any, Final

from trading_intel.domain.candles import ClosedCandle, Timeframe
from trading_intel.domain.patterns import DetectedPattern, Direction
from trading_intel.domain.signals import Action, EntryType, Side
from trading_intel.market_structure.regime import RegimeView
from trading_intel.market_structure.structure import Trend, analyse_structure
from trading_intel.market_structure.swings import find_swings
from trading_intel.pattern_detection.candles import (
    engulfing,
    pin_bars_and_dojis,
    trend_candle_patterns,
)
from trading_intel.pattern_detection.chart_patterns import chart_patterns
from trading_intel.risk_management.models import TradeProposal
from trading_intel.technical_analysis.series import CandleSeries
from trading_intel.technical_analysis.volatility import atr
from trading_intel.technical_analysis.volume import relative_volume
from trading_intel.trade_signals.baseline import BaselineDecision
from trading_intel.trade_signals.catalogue import ExtraLevel, build_catalogue, targets_beyond

STRATEGY_NAME: Final = "pattern_breakout"
STRATEGY_VERSION: Final = 1
SETUP_TIMEFRAME: Final = Timeframe.H1
CATALOGUE_LOOKBACK: Final = 400


@dataclass(frozen=True)
class PatternParameters:
    """Every value was fixed before the first run. Changing one makes a new trial."""

    stop_buffer_atr: float = 0.25  # Beyond the invalidation level, where sweeps reach.
    min_target_r: float = 2.0  # The same rule as the baseline, for a fair comparison.
    expiry_candles: int = 4
    leverage: str = "1"
    require_candle: bool = False  # Trial 2 sets this.
    candle_window: int = 3
    skip_volatile: bool = False  # Version 2 (D037): no new trade in the most volatile quarter.

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class TrendView:
    """A higher timeframe's swing trend as known at a moment: its last closed candle."""

    def __init__(self, candles: Sequence[ClosedCandle]) -> None:
        series = CandleSeries.of(candles)
        self._close_times = list(series.close_time)
        self._trend = analyse_structure(series, find_swings(series)).trend

    def at(self, moment: datetime) -> Trend:
        position = bisect_right(self._close_times, moment) - 1
        return self._trend[position] if position >= 0 else "none"


def _round_away(value: Decimal, tick: Decimal, side: Side) -> Decimal:
    rounding = ROUND_FLOOR if side is Side.LONG else ROUND_CEILING
    return (value / tick).to_integral_value(rounding=rounding) * tick


class PatternStrategy:
    """Patterns, trends and ATR are computed once over the whole history.

    Each of them is prefix-stable, which tests prove, so reading the value at a candle gives
    exactly what a live run would have known at that candle.
    """

    timeframe: Final = SETUP_TIMEFRAME

    def __init__(
        self,
        setup: Sequence[ClosedCandle],
        middle: Sequence[ClosedCandle],
        higher: Sequence[ClosedCandle],
        tick: Decimal,
        parameters: PatternParameters | None = None,
    ) -> None:
        self.parameters = parameters or PatternParameters()
        self.series = CandleSeries.of(setup)
        self.tick = tick
        self.atr = atr(self.series)
        self.middle = TrendView(middle)
        self.higher = TrendView(higher)
        self.regimes = RegimeView(CandleSeries.of(higher))
        self.index_of = {moment: i for i, moment in enumerate(self.series.close_time)}
        found = chart_patterns(self.series, self.atr, relative_volume(self.series.volume))
        self.breakouts: dict[datetime, list[DetectedPattern]] = {}
        for pattern in found:
            self.breakouts.setdefault(pattern.detected_at, []).append(pattern)
        candles = [
            *engulfing(self.series),
            *pin_bars_and_dojis(self.series),
            *trend_candle_patterns(self.series, self.atr),
        ]
        self.candles: dict[datetime, list[DetectedPattern]] = {}
        for pattern in candles:
            if pattern.direction is not Direction.NEUTRAL:
                self.candles.setdefault(pattern.detected_at, []).append(pattern)

    def trends_at(self, moment: datetime) -> tuple[Trend, Trend]:
        return self.middle.at(moment), self.higher.at(moment)

    def _confirming_candle(self, index: int, direction: Direction) -> DetectedPattern | None:
        start = max(index - self.parameters.candle_window + 1, 0)
        for position in range(index, start - 1, -1):
            for pattern in self.candles.get(self.series.close_time[position], []):
                if pattern.direction is direction:
                    return pattern
        return None

    def decide(self, moment: datetime) -> BaselineDecision:
        """Decide using only what was known when the 1H candle closed at `moment`."""
        index = self.index_of.get(moment)
        if index is None:
            return BaselineDecision(Action.NO_TRADE, moment, ("no setup candle closed",))
        found = self.breakouts.get(moment, [])
        if not found:
            return BaselineDecision(Action.NO_TRADE, moment, ("no pattern breakout",))
        middle, higher = self.trends_at(moment)

        def agrees(pattern: DetectedPattern) -> bool:
            wanted: Trend = "up" if pattern.direction is Direction.BULLISH else "down"
            return middle == wanted == higher

        aligned = [p for p in found if agrees(p)]
        if not aligned:
            directions = " and ".join(sorted({p.direction.value for p in found}))
            return BaselineDecision(
                Action.NO_TRADE,
                moment,
                (f"{directions} breakout against the trend: 4H {middle}, 1D {higher}",),
                patterns=tuple(found),
            )
        if self.parameters.skip_volatile and self.regimes.at(moment).volatility == "volatile":
            return BaselineDecision(
                Action.NO_TRADE,
                moment,
                ("daily volatility is in the top quarter of its year",),
                patterns=tuple(aligned),
            )
        candidates = aligned
        confirmation: DetectedPattern | None = None
        if self.parameters.require_candle:
            candidates = [p for p in aligned if self._confirming_candle(index, p.direction)]
            if not candidates:
                return BaselineDecision(
                    Action.NO_TRADE, moment, ("no confirming candle",), patterns=tuple(aligned)
                )
        pattern = max(candidates, key=lambda p: (p.strength, p.pattern_type))
        if self.parameters.require_candle:
            confirmation = self._confirming_candle(index, pattern.direction)
        return self._propose(index, moment, pattern, confirmation)

    def _propose(
        self,
        index: int,
        moment: datetime,
        pattern: DetectedPattern,
        confirmation: DetectedPattern | None,
    ) -> BaselineDecision:
        params, tick = self.parameters, self.tick
        side = Side.LONG if pattern.direction is Direction.BULLISH else Side.SHORT
        evidence = pattern.evidence
        extra: list[ExtraLevel] = [
            (
                "pattern_invalidation",
                float(evidence["invalidation"]),
                f"{pattern.pattern_type} invalidation",
            )
        ]
        for multiple, level in zip(("1x", "2x"), evidence["measured_moves"], strict=True):
            extra.append(
                ("measured_move", float(level), f"{pattern.pattern_type} {multiple} measured move")
            )
        start = index - CATALOGUE_LOOKBACK + 1
        window = self.series.window(start, index + 1)
        catalogue = build_catalogue(
            window, find_swings(window), self.atr[max(start, 0) : index + 1], tick, extra
        )
        patterns = (pattern,) if confirmation is None else (pattern, confirmation)
        if catalogue is None:
            return BaselineDecision(
                Action.NO_TRADE, moment, ("volatility is still warming up",), patterns=patterns
            )
        entry = catalogue.close
        buffer = Decimal(str(params.stop_buffer_atr)) * catalogue.atr
        stop = _round_away(Decimal(str(evidence["invalidation"])) - side.sign * buffer, tick, side)
        risk = side.sign * (entry - stop)
        if risk <= 0:
            return BaselineDecision(
                Action.NO_TRADE, moment, ("invalidation is beyond the close",), patterns=patterns
            )
        targets = targets_beyond(catalogue, side, entry, risk, Decimal(str(params.min_target_r)))
        if not targets:
            return BaselineDecision(
                Action.NO_TRADE, moment, ("no reachable target",), patterns=patterns
            )
        condition = "close below" if side is Side.LONG else "close above"
        trend = "up" if side is Side.LONG else "down"
        return BaselineDecision(
            action=Action.BUY if side is Side.LONG else Action.SELL,
            as_of=moment,
            reasons=(f"{pattern.pattern_type} breakout with 4H and 1D {trend}",),
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
            patterns=patterns,
        )
