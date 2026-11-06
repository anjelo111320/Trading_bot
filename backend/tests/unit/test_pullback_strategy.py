"""The trend pullback strategy. All candles and levels are synthetic."""

from datetime import datetime
from decimal import Decimal

from tests.unit.test_pattern_strategy import HOURS, TICK, waves
from trading_intel.domain.candles import Timeframe
from trading_intel.domain.patterns import DetectedPattern, Direction
from trading_intel.domain.signals import Action, Side
from trading_intel.trade_signals.catalogue import CatalogueLevel, LevelCatalogue
from trading_intel.trade_signals.pattern_strategy import PatternStrategy
from trading_intel.trade_signals.pullback_strategy import PullbackStrategy

INDEX = len(HOURS) - 1
MOMENT = HOURS[INDEX].close_time
CLOSE = Decimal("112.00")  # The last test candle: low 109.3, high 112.2.


class FixedLevels(PullbackStrategy):
    """The real decision rules over a hand-made catalogue, so each rule can be tested alone."""

    def __init__(self, base: PatternStrategy, levels: list[tuple[str, str]]) -> None:
        super().__init__(base)
        self.levels = levels

    def catalogue_at(self, index: int) -> LevelCatalogue:
        return LevelCatalogue(
            as_of=MOMENT,
            close=CLOSE,
            atr=Decimal("1.0"),
            levels=tuple(
                CatalogueLevel(
                    id=f"L{number}",
                    kind=kind,  # type: ignore[arg-type]
                    price=Decimal(price),
                    timeframe=Timeframe.H1,
                    position="above" if Decimal(price) > CLOSE else "below",
                    evidence="test level",
                )
                for number, (kind, price) in enumerate(self.levels, start=1)
            ),
        )


def setup(up: bool, direction: Direction, levels: list[tuple[str, str]]) -> FixedLevels:
    base = PatternStrategy(HOURS, waves(Timeframe.H4, up), waves(Timeframe.D1, up), TICK)
    base.candles = {MOMENT: [candle(direction, MOMENT)]}
    return FixedLevels(base, levels)


def candle(direction: Direction, at: datetime) -> DetectedPattern:
    kind = "bullish_engulfing" if direction is Direction.BULLISH else "bearish_engulfing"
    return DetectedPattern(kind, direction, at, at, strength=60.0)


TARGETS_ABOVE = [("resistance", "118.00"), ("swing_high", "121.00"), ("resistance", "125.00")]
TARGETS_BELOW = [("support", "111.00"), ("swing_low", "110.00"), ("support", "108.00")]


def test_a_with_trend_reversal_at_support_is_a_buy() -> None:
    strategy = setup(True, Direction.BULLISH, [("support", "109.40"), *TARGETS_ABOVE])
    decision = strategy.decide(MOMENT)
    assert decision.action is Action.BUY
    proposal = decision.proposal
    assert proposal is not None and proposal.side is Side.LONG
    # Below the lower of the level and the candle's low, by 0.25 ATR.
    assert proposal.stop == Decimal("109.05")
    risk = proposal.entry - proposal.stop
    assert proposal.targets == (Decimal("118.00"), Decimal("121.00"), Decimal("125.00"))
    assert all(target - proposal.entry >= 2 * risk for target in proposal.targets)
    assert decision.reasons == ("bullish_engulfing at support 109.40 with 4H and 1D up",)


def test_a_short_at_resistance_mirrors_the_long() -> None:
    strategy = setup(False, Direction.BEARISH, [("resistance", "112.10"), *TARGETS_BELOW])
    decision = strategy.decide(MOMENT)
    assert decision.action is Action.SELL
    proposal = decision.proposal
    assert proposal is not None and proposal.side is Side.SHORT
    assert proposal.stop == Decimal("112.45")
    assert proposal.targets == (Decimal("111.00"), Decimal("110.00"), Decimal("108.00"))


def test_a_reversal_away_from_any_level_is_no_trade() -> None:
    strategy = setup(True, Direction.BULLISH, [("support", "108.50"), *TARGETS_ABOVE])
    decision = strategy.decide(MOMENT)
    assert decision.action is Action.NO_TRADE
    assert decision.reasons == ("the reversal is not at a support level",)


def test_only_structural_levels_count_as_support() -> None:
    strategy = setup(True, Direction.BULLISH, [("atr_projection", "109.40"), *TARGETS_ABOVE])
    assert strategy.decide(MOMENT).reasons == ("the reversal is not at a support level",)


def test_a_candle_against_the_trend_is_ignored() -> None:
    strategy = setup(True, Direction.BEARISH, [("resistance", "112.10"), *TARGETS_BELOW])
    assert strategy.decide(MOMENT).reasons == ("no reversal candle with the trend",)


def test_trends_that_disagree_give_no_trade() -> None:
    base = PatternStrategy(HOURS, waves(Timeframe.H4, True), waves(Timeframe.D1, False), TICK)
    base.candles = {MOMENT: [candle(Direction.BULLISH, MOMENT)]}
    decision = FixedLevels(base, [("support", "109.40"), *TARGETS_ABOVE]).decide(MOMENT)
    assert decision.reasons == ("trends disagree: 4H up, 1D down",)


def test_no_target_two_r_away_is_no_trade() -> None:
    strategy = setup(True, Direction.BULLISH, [("support", "109.40"), ("resistance", "114.00")])
    assert strategy.decide(MOMENT).reasons == ("no reachable target",)


def test_the_real_catalogue_is_built_from_candles_closed_by_then() -> None:
    base = PatternStrategy(HOURS, waves(Timeframe.H4, True), waves(Timeframe.D1, True), TICK)
    catalogue = PullbackStrategy(base).catalogue_at(INDEX - 5)
    assert catalogue is not None
    assert catalogue.as_of == HOURS[INDEX - 5].close_time
    assert catalogue.close == Decimal(str(HOURS[INDEX - 5].close))
