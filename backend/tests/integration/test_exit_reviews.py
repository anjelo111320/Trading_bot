"""Claude's exit advice in shadow mode (D051), on real PostgreSQL with a stub reviewer.

A paper trade rises to about +1.5R, stalls for two hours, then falls to its stop. Test data,
not market data. No request reaches Anthropic.
"""

from datetime import timedelta
from decimal import Decimal as D
from typing import Any

import pytest

from tests.integration import test_trading_flow as flow
from tests.integration.test_trading_flow import NOW, World, approve, bar, rows
from tests.quant_data import candle
from trading_intel.ai_analyst.exit_review import MODEL, ExitAdvice, ReviewResult
from trading_intel.ai_analyst.exit_service import ExitReviewService
from trading_intel.database.repositories.candles import CandleRepository
from trading_intel.database.repositories.exit_reviews import ExitReviewRepository
from trading_intel.database.repositories.news import NewsRepository
from trading_intel.database.repositories.operations import MarketRepository
from trading_intel.database.repositories.paper import PaperRepository
from trading_intel.domain.base import DataOrigin
from trading_intel.domain.candles import ClosedCandle, Timeframe
from trading_intel.news_intelligence.classifier import Usage

pytestmark = pytest.mark.integration

world = flow.world  # The trading flow's fixture: one coin, a live book and an owner.

STALL_CLOSE = Timeframe.M15.close_time(NOW + timedelta(minutes=150))  # 2h45m after entry.


class StubReviewer:
    def __init__(self, action: str = "take_profit_now") -> None:
        self.action = action
        self.asked: list[str] = []

    async def review(self, facts: str) -> ReviewResult:
        self.asked.append(facts)
        advice = ExitAdvice.model_validate({"action": self.action, "reason": "Stalled 2h."})
        return ReviewResult(
            "advised", advice, MODEL, Usage(700, 60, 560, 0), advice.model_dump_json()
        )


def quarter(world: World, index: int, open_: str, high: str, low: str, close: str) -> ClosedCandle:
    base = candle(0, float(open_), float(high), float(low), float(close), 5000.0, Timeframe.M15)
    at = NOW + timedelta(minutes=15 * index)
    return base.model_copy(
        update={
            "provider_id": world.provider_id,
            "instrument_id": world.instrument.id,
            "open_time": at,
            "close_time": Timeframe.M15.close_time(at),
            "data_origin": DataOrigin.LIVE,
        }
    )


async def stalled_trade(world: World) -> None:
    """Entry at 100.03 with 2.00 of risk, a best of 103.00 a minute later, then flat."""
    assert (await approve(world)).approved
    minutes = [bar(world, 0, "100", "100.2", "99.9", "100.1")]
    minutes.append(bar(world, 1, "100.1", "103", "100.1", "102.8"))
    minutes += [bar(world, k, "102.5", "102.6", "102.4", "102.5") for k in range(2, 170)]
    quarters = [quarter(world, 0, "100", "103", "99.9", "102.5")]
    quarters += [quarter(world, i, "102.5", "102.6", "102.4", "102.5") for i in range(1, 11)]
    await world.candles.insert(minutes + quarters)


def service(world: World, reviewer: Any = None, limit: D = D(3)) -> ExitReviewService:
    engine = world.signals._rules._engine
    return ExitReviewService(
        CandleRepository(engine), MarketRepository(engine), PaperRepository(engine),
        ExitReviewRepository(engine), NewsRepository(engine), world.clock, reviewer, limit,
    )  # fmt: skip


async def test_a_stalled_trade_is_reviewed_once_and_its_advice_scored(world: World) -> None:
    await stalled_trade(world)
    stub = StubReviewer()
    exits = service(world, stub)
    assert await exits.review(world.provider_id, world.instrument, STALL_CLOSE) == 1
    assert await exits.review(world.provider_id, world.instrument, STALL_CLOSE) == 0
    assert len(stub.asked) == 1, "asked once: the same best never pays twice"
    assert "checks: stall past +1R" in stub.asked[0]
    [review] = await rows("SELECT * FROM ai_exit_reviews")
    assert review["status"] == "advised" and review["action"] == "take_profit_now"
    assert review["checks"] == ["stall past +1R"] and review["facts"] == stub.asked[0]
    assert 1 < review["progress_r"] < D("1.3")  # 102.50 against an entry near 100.03.
    assert review["input_tokens"] == 1260 and review["output_tokens"] == 60
    [usage] = await rows("SELECT purpose, model, cost_usd FROM api_usage")
    assert usage["purpose"] == "exit_review" and usage["model"] == MODEL
    assert usage["cost_usd"] == D("0.0001056")  # 700 x 0.10 + 60 x 0.50 + 560 x 0.01, per MTok.
    paper = await rows("SELECT status FROM paper_positions")
    assert paper[0]["status"] in ("pending_entry", "open"), "shadow mode changes no trade"

    # Then the trade falls to its stop at 98.00.
    await world.candles.insert([bar(world, 170, "102.5", "102.5", "97", "97.5")])
    world.clock.advance(3 * 3600)
    await world.paper.sync(world.provider_id, world.instrument.id)
    assert (await rows("SELECT status FROM paper_positions"))[0]["status"] == "closed"
    assert await exits.score_finished() == 1
    [scored] = await rows("SELECT own_r, advised_r FROM ai_exit_reviews")
    [outcome] = await rows("SELECT r_multiple FROM trade_outcomes")
    assert scored["own_r"] == pytest.approx(outcome["r_multiple"], abs=D("0.000001"))
    assert scored["own_r"] < -1 < 1 < scored["advised_r"], "the advice would have kept +1.1R"
    assert await exits.score_finished() == 0, "scored once"
    repository = ExitReviewRepository(world.signals._rules._engine)
    summary = await repository.summary()
    assert summary["statuses"] == {"advised": 1} and summary["acted"] == 1
    assert summary["change"] == scored["advised_r"] - scored["own_r"]
    [shown] = await repository.recent()
    assert shown["account"] == "Paper" and shown["action"] == "take_profit_now"


async def test_without_a_key_checks_are_counted_and_nothing_is_paid(world: World) -> None:
    await stalled_trade(world)
    assert await service(world).review(world.provider_id, world.instrument, STALL_CLOSE) == 1
    [review] = await rows("SELECT status, action, model FROM ai_exit_reviews")
    assert dict(review) == {"status": "not_asked", "action": None, "model": None}
    assert await rows("SELECT * FROM api_usage") == []


async def test_a_spent_daily_budget_skips_the_call(world: World) -> None:
    await stalled_trade(world)
    stub = StubReviewer()
    assert await service(world, stub, D(0)).review(world.provider_id, world.instrument, STALL_CLOSE)
    assert stub.asked == []
    [review] = await rows("SELECT status FROM ai_exit_reviews")
    assert review["status"] == "skipped_budget"


async def test_hold_advice_scores_as_the_trade_itself(world: World) -> None:
    await stalled_trade(world)
    exits = service(world, StubReviewer("hold"))
    await exits.review(world.provider_id, world.instrument, STALL_CLOSE)
    await world.candles.insert([bar(world, 170, "102.5", "102.5", "97", "97.5")])
    world.clock.advance(3 * 3600)
    await world.paper.sync(world.provider_id, world.instrument.id)
    assert await exits.score_finished() == 1
    [scored] = await rows("SELECT own_r, advised_r FROM ai_exit_reviews")
    assert scored["own_r"] == scored["advised_r"]
