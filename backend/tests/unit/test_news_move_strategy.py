"""The news move strategy's pre-registered rules (docs/40, D056). Test data, not market data."""

from datetime import UTC, datetime
from decimal import Decimal as D
from typing import Any

import pytest

from tests.quant_data import candle
from tests.unit.test_backtesting import INSTRUMENT
from trading_intel.core.clock import FixedClock
from trading_intel.domain.candles import ClosedCandle
from trading_intel.domain.signals import Action, Side
from trading_intel.trade_signals.news_move_strategy import NewsMoveParameters, NewsMoveStrategy
from trading_intel.trade_signals.service import SignalService

TICK = D("0.01")


def quiet(count: int = 30) -> list[ClosedCandle]:
    """Calm hours: a 2-point range around 100, so ATR(14) settles at 2."""
    return [candle(i, 100, 101, 99, 100) for i in range(count)]


def decide(last: ClosedCandle, hours: list[ClosedCandle] | None = None) -> Any:
    candles = [*(hours or quiet()), last]
    return NewsMoveStrategy(candles, TICK).decide(last.close_time)


def test_the_rules_are_the_registered_ones() -> None:
    params = NewsMoveParameters()
    assert (params.atr_hours, params.move_atr, params.strong_close) == (14, 1.5, 0.7)
    assert params.stop_atr == 1.5 and params.targets_r == (2.0, 3.0)


def test_a_strong_rise_with_a_strong_close_is_a_long_with_a_1_5_atr_stop() -> None:
    decision = decide(candle(30, 100, 104.2, 99.8, 104))
    proposal = decision.proposal
    assert decision.action is Action.BUY and proposal.side is Side.LONG
    assert decision.setup_atr == D(2), "the ATR before the move, not inflated by it"
    assert proposal.entry == D("104.00") and proposal.stop == D("101.00")
    assert proposal.targets == (D("110.00"), D("113.00")), "2R and 3R"


def test_a_strong_fall_is_a_short() -> None:
    decision = decide(candle(30, 100, 100.2, 95.8, 96))
    proposal = decision.proposal
    assert proposal.side is Side.SHORT and proposal.stop == D("99.00")
    assert proposal.targets == (D("90.00"), D("87.00"))


@pytest.mark.parametrize(
    ("last", "why"),
    [
        (candle(30, 100, 102.9, 99, 102.8), "a body of 2.8 is under 1.5 ATR (3)"),
        (candle(30, 100, 108, 99, 104), "the close is in the middle of the range"),
        (candle(30, 100, 100, 100, 100), "a candle with no range"),
    ],
)
def test_weak_or_small_moves_are_not_traded(last: ClosedCandle, why: str) -> None:
    decision = decide(last)
    assert decision.action is Action.NO_TRADE and decision.proposal is None, why


def test_nothing_is_decided_before_atr_exists() -> None:
    decision = NewsMoveStrategy([candle(0, 100, 104.2, 99.8, 104)], TICK).decide(
        candle(0, 100, 104.2, 99.8, 104).close_time
    )
    assert decision.action is Action.NO_TRADE


class NewsSays:
    def __init__(self, found: str = "aligned", direction: str = "bullish", fails: bool = False):
        self.found, self.direction, self.fails = found, direction, fails

    async def alignment(self, instrument_id: int, side: Side, at: datetime) -> Any:
        if self.fails:
            raise RuntimeError("news store unreachable")
        return self.found, {"direction": self.direction}


def service(news: NewsSays | None) -> SignalService:
    clock = FixedClock(datetime(2026, 11, 11, tzinfo=UTC))
    return SignalService(None, None, None, None, None, None, None, clock, news=news)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("news", "reason"),
    [
        (NewsSays("conflicting", "bearish"), "news is bearish, not with the move"),
        (NewsSays("neutral", "neutral"), "news is neutral, not with the move"),
        (NewsSays(fails=True), "the news reading failed"),
        (None, "no news reading"),
    ],
)
async def test_a_move_without_agreeing_news_is_never_traded(
    news: NewsSays | None, reason: str
) -> None:
    move = decide(candle(30, 100, 104.2, 99.8, 104))
    decision = await service(news)._news_confirms(INSTRUMENT, move)
    assert decision.action is Action.NO_TRADE and decision.proposal is None
    assert decision.reasons[-1] == reason


async def test_a_move_the_news_agrees_with_keeps_its_prices() -> None:
    move = decide(candle(30, 100, 104.2, 99.8, 104))
    decision = await service(NewsSays())._news_confirms(INSTRUMENT, move)
    assert decision.proposal == move.proposal, "news changes no price, stop or target"
    assert decision.reasons[-1] == "news is bullish, with the move"
