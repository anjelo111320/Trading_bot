"""Trend pullback strategy, version 1. Pre-registered in docs/31-PULLBACK-STRATEGY.md.

Hypothesis, stated before any test: with the 4H and 1D swing trends agreeing, a with-trend
1H reversal candle at a Python level starts a move that pays for a 2:1 trade after costs,
and does better than random entries with the same trend filter and exits. This is an idea
to test, not a claim that it works.
"""

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Any, Final

from trading_intel.domain.candles import Timeframe
from trading_intel.domain.patterns import DetectedPattern, Direction
from trading_intel.domain.signals import Action, EntryType, Side
from trading_intel.market_structure.swings import find_swings
from trading_intel.risk_management.models import TradeProposal
from trading_intel.trade_signals.baseline import BaselineDecision
from trading_intel.trade_signals.catalogue import LevelCatalogue, build_catalogue, targets_beyond
from trading_intel.trade_signals.pattern_strategy import CATALOGUE_LOOKBACK, PatternStrategy

STRATEGY_NAME: Final = "trend_pullback"
STRATEGY_VERSION: Final = 1
SUPPORTS: Final = frozenset({"support", "swing_low"})
RESISTANCES: Final = frozenset({"resistance", "swing_high"})


@dataclass(frozen=True)
class PullbackParameters:
    """Every value was fixed before the first run. Changing one makes a new trial."""

    touch_atr: float = 0.25  # How close the candle's extreme must come to the level.
    stop_buffer_atr: float = 0.25  # Beyond the level or the extreme, where sweeps reach.
    min_target_r: float = 2.0  # The same rule as the other strategies.
    expiry_candles: int = 4
    leverage: str = "1"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _round_away(value: Decimal, tick: Decimal, side: Side) -> Decimal:
    rounding = ROUND_FLOOR if side is Side.LONG else ROUND_CEILING
    return (value / tick).to_integral_value(rounding=rounding) * tick


class PullbackStrategy:
    """Reads trends, candle signals and ATR from a pattern strategy on the same candles.

    Those are computed once and are prefix-stable, so a decision at a candle uses only what a
    live run would have known then. The catalogue is built only at with-trend candle signals,
    and each decision is kept, so repeated runs over the same history agree and cost less.
    """

    timeframe: Final = Timeframe.H1

    def __init__(self, base: PatternStrategy, parameters: PullbackParameters | None = None) -> None:
        self.base = base
        self.parameters = parameters or PullbackParameters()
        self._decided: dict[datetime, BaselineDecision] = {}

    def catalogue_at(self, index: int) -> LevelCatalogue | None:
        base = self.base
        start = index - CATALOGUE_LOOKBACK + 1
        window = base.series.window(start, index + 1)
        return build_catalogue(
            window, find_swings(window), base.atr[max(start, 0) : index + 1], base.tick
        )

    def decide(self, moment: datetime) -> BaselineDecision:
        """Decide using only what was known when the 1H candle closed at `moment`."""
        decision = self._decided.get(moment)
        if decision is None:
            decision = self._decided[moment] = self._decide(moment)
        return decision

    def _decide(self, moment: datetime) -> BaselineDecision:
        base = self.base
        index = base.index_of.get(moment)
        if index is None:
            return BaselineDecision(Action.NO_TRADE, moment, ("no setup candle closed",))
        middle, higher = base.trends_at(moment)
        if middle == higher == "up":
            side, wanted = Side.LONG, Direction.BULLISH
        elif middle == higher == "down":
            side, wanted = Side.SHORT, Direction.BEARISH
        else:
            return BaselineDecision(
                Action.NO_TRADE, moment, (f"trends disagree: 4H {middle}, 1D {higher}",)
            )
        candle = next((p for p in base.candles.get(moment, []) if p.direction is wanted), None)
        if candle is None:
            return BaselineDecision(Action.NO_TRADE, moment, ("no reversal candle with the trend",))
        catalogue = self.catalogue_at(index)
        if catalogue is None:
            return BaselineDecision(
                Action.NO_TRADE, moment, ("volatility is still warming up",), patterns=(candle,)
            )
        return self._propose(index, moment, side, candle, catalogue)

    def _propose(
        self,
        index: int,
        moment: datetime,
        side: Side,
        candle: DetectedPattern,
        catalogue: LevelCatalogue,
    ) -> BaselineDecision:
        params, tick, series = self.parameters, self.base.tick, self.base.series
        unit = catalogue.atr
        long = side is Side.LONG
        extreme = Decimal(str(float(series.low[index] if long else series.high[index])))
        kinds, position = (SUPPORTS, "below") if long else (RESISTANCES, "above")
        reach = Decimal(str(params.touch_atr)) * unit
        touched = [
            level
            for level in catalogue.levels
            if level.kind in kinds
            and level.position == position
            and abs(level.price - extreme) <= reach
        ]
        if not touched:
            where = "support" if long else "resistance"
            return BaselineDecision(
                Action.NO_TRADE,
                moment,
                (f"the reversal is not at a {where} level",),
                patterns=(candle,),
            )
        level = min(touched, key=lambda v: abs(v.price - extreme))
        protect = min(level.price, extreme) if long else max(level.price, extreme)
        entry = catalogue.close
        stop = _round_away(
            protect - side.sign * Decimal(str(params.stop_buffer_atr)) * unit, tick, side
        )
        risk = side.sign * (entry - stop)
        if risk <= 0 or stop <= 0:
            return BaselineDecision(
                Action.NO_TRADE, moment, ("the stop is out of range",), patterns=(candle,)
            )
        targets = targets_beyond(catalogue, side, entry, risk, Decimal(str(params.min_target_r)))
        if not targets:
            return BaselineDecision(
                Action.NO_TRADE, moment, ("no reachable target",), patterns=(candle,)
            )
        condition = "close below" if long else "close above"
        trend = "up" if long else "down"
        return BaselineDecision(
            action=Action.BUY if long else Action.SELL,
            as_of=moment,
            reasons=(
                f"{candle.pattern_type} at {level.kind} {level.price} with 4H and 1D {trend}",
            ),
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
            setup_atr=unit,
            patterns=(candle,),
        )
