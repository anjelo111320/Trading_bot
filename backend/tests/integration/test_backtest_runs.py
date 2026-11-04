from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from trading_intel.database.repositories.backtests import (
    BacktestRunRepository,
    HoldoutAlreadyUsedError,
)
from trading_intel.database.repositories.signals import SignalRepository

pytestmark = pytest.mark.integration

WINDOW = (datetime(2025, 11, 1, tzinfo=UTC), datetime(2026, 11, 1, tzinfo=UTC))


async def claim(engine: AsyncEngine) -> tuple[BacktestRunRepository, UUID, UUID]:
    strategy = await SignalRepository(engine).ensure_strategy(
        "pattern_breakout", 2, {"skip_volatile": True}
    )
    runs = BacktestRunRepository(engine)
    dataset = await runs.ensure_dataset("holdout-test", {"symbols": ["BTCUSDT"]})
    return runs, strategy, dataset


async def test_a_strategy_configuration_gets_one_holdout_run(app_engine: AsyncEngine) -> None:
    runs, strategy, dataset = await claim(app_engine)
    assert await runs.ensure_dataset("holdout-test", {"symbols": ["BTCUSDT"]}) == dataset
    first = await runs.start_holdout(strategy, dataset, WINDOW, {"stress": "1"}, "sha")
    await runs.finish(first, "succeeded", {"trades": 3})
    with pytest.raises(HoldoutAlreadyUsedError):
        await runs.start_holdout(strategy, dataset, WINDOW, {"stress": "1"}, "sha")


async def test_a_failed_holdout_run_can_be_claimed_again(app_engine: AsyncEngine) -> None:
    runs, strategy, dataset = await claim(app_engine)
    first = await runs.start_holdout(strategy, dataset, WINDOW, {}, "sha")
    await runs.finish(first, "failed", {"error": "crashed"})
    assert await runs.start_holdout(strategy, dataset, WINDOW, {}, "sha") != first
