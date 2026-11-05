"""Forecast storage, timing rules and resolution, with a stand-in model.

The stand-in writes fixed test paths. It is not Kronos, and its numbers mean nothing.
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import asyncpg
import numpy as np
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.conftest import make_settings
from tests.integration.support import SUPERUSER_URL
from tests.quant_data import candle
from trading_intel.core.clock import FixedClock
from trading_intel.database.engine import create_engine
from trading_intel.database.repositories.candles import CandleRepository
from trading_intel.database.repositories.forecasts import ForecastRepository
from trading_intel.database.repositories.reference import ReferenceRepository
from trading_intel.domain.base import DataOrigin
from trading_intel.domain.candles import ClosedCandle, Timeframe
from trading_intel.forecasting.evidence import LABEL
from trading_intel.forecasting.kronos import ForecastUnavailableError, KronosConfig, ModelForecast
from trading_intel.forecasting.paths import SampledPaths
from trading_intel.forecasting.service import ForecastService
from trading_intel.forecasting.time_machine import TimeMachineParameters

pytestmark = pytest.mark.integration

HISTORY = 115  # 100 for the baseline, 15 for ATR.


class StandInModel:
    def __init__(self) -> None:
        self.config = KronosConfig(paths=5, horizon=4, context=50)
        self.calls = 0

    def forecast(self, candles: Sequence[ClosedCandle]) -> ModelForecast:
        self.calls += 1
        last = candles[-1]
        close = float(last.close)
        sampled = np.array(
            [
                [[close, close * 1.02, close * 0.98, close * (1 + (i - 1) / 100)]] * 4
                for i in range(5)
            ]
        )
        paths = SampledPaths("stand-in", last.timeframe, last.close_time, close, sampled)
        return ModelForecast(paths, self.config, 50)


async def seed(count: int, skip: int | None = None) -> tuple[int, int, list[ClosedCandle]]:
    ingest = create_engine(make_settings().ingest_database_url)
    listed = await ReferenceRepository(ingest).provider_instruments("binance_usdm")
    provider, instrument = listed[0].provider_id, listed[0].instrument.id
    rows, previous = [], 100.0
    for index in range(count):
        close = 100.0 + (index % 9) - (index % 4) + index * 0.05
        row = candle(index, previous, max(previous, close) + 1, min(previous, close) - 1, close)
        rows.append(
            row.model_copy(
                update={
                    "provider_id": provider,
                    "instrument_id": instrument,
                    "data_origin": DataOrigin.BACKFILL,
                }
            )
        )
        previous = close
    await CandleRepository(ingest).insert([r for i, r in enumerate(rows) if i != skip])
    await ingest.dispose()
    return provider, instrument, rows


def service(
    engine: AsyncEngine, model: StandInModel, clock: FixedClock, holdout: datetime | None = None
) -> ForecastService:
    return ForecastService(
        CandleRepository(engine),
        ForecastRepository(engine),
        model,
        clock,
        holdout_start=holdout or datetime(2027, 1, 1, tzinfo=UTC),
        baseline=TimeMachineParameters(lookback=100, paths=200),
    )


async def test_a_forecast_is_stored_once_and_reused(app_engine: AsyncEngine) -> None:
    provider, instrument, rows = await seed(HISTORY)
    as_of = rows[-1].close_time
    model = StandInModel()
    forecasts = service(app_engine, model, FixedClock(as_of + timedelta(minutes=1)))
    first = await forecasts.forecast(provider, instrument, Timeframe.H1, as_of, "manual")
    assert first.summary["count"] == 5 and first.summary["horizon"] == 4
    assert first.baseline["parameters"]["lookback"] == 100
    assert first.baseline["summary"]["count"] == 200
    assert first.last_close == rows[-1].close and first.atr > 0
    again = await forecasts.forecast(provider, instrument, Timeframe.H1, as_of, "setup")
    assert again.id == first.id and again.reason == "manual"
    assert model.calls == 1


async def test_stale_incomplete_or_gappy_candles_are_refused(app_engine: AsyncEngine) -> None:
    provider, instrument, rows = await seed(HISTORY + 10, skip=HISTORY - 20)
    as_of = rows[-1].close_time
    model = StandInModel()
    late = service(app_engine, model, FixedClock(as_of + timedelta(hours=3)))
    with pytest.raises(ForecastUnavailableError, match="too old"):
        await late.forecast(provider, instrument, Timeframe.H1, as_of, "manual")
    fresh = service(app_engine, model, FixedClock(as_of + timedelta(minutes=1)))
    with pytest.raises(ForecastUnavailableError, match="gap"):
        await fresh.forecast(provider, instrument, Timeframe.H1, as_of, "manual")
    unstored = as_of + timedelta(hours=1)  # A close the database does not hold.
    early = service(app_engine, model, FixedClock(unstored + timedelta(minutes=1)))
    with pytest.raises(ForecastUnavailableError, match="not stored"):
        await early.forecast(provider, instrument, Timeframe.H1, unstored, "manual")
    assert model.calls == 0


async def test_study_forecasts_must_resolve_before_the_holdout(app_engine: AsyncEngine) -> None:
    provider, instrument, rows = await seed(HISTORY)
    as_of = rows[-1].close_time
    clock = FixedClock(as_of + timedelta(days=30))
    guarded = service(app_engine, StandInModel(), clock, holdout=as_of + timedelta(hours=2))
    with pytest.raises(ForecastUnavailableError, match="before the holdout"):
        await guarded.forecast(provider, instrument, Timeframe.H1, as_of, "study")
    allowed = service(app_engine, StandInModel(), clock, holdout=as_of + timedelta(days=2))
    stored = await allowed.forecast(provider, instrument, Timeframe.H1, as_of, "study")
    assert stored.reason == "study"


async def test_forecasts_resolve_once_their_horizon_has_passed(app_engine: AsyncEngine) -> None:
    provider, instrument, rows = await seed(HISTORY + 4)
    history, after = rows[:HISTORY], rows[HISTORY:]
    as_of = history[-1].close_time
    clock = FixedClock(as_of + timedelta(minutes=1))
    forecasts = service(app_engine, StandInModel(), clock)
    stored = await forecasts.forecast(provider, instrument, Timeframe.H1, as_of, "manual")
    assert await forecasts.resolve_due() == (0, 1)
    clock.advance(4 * 3600)
    assert await forecasts.resolve_due() == (1, 0)
    assert await forecasts.resolve_due() == (0, 0)

    record = await forecasts.track_record(Timeframe.H1)
    assert record.count == 1 and record.status == "too few forecasts"
    facts = await forecasts.facts(stored, levels=[("L1", after[0].close)])
    assert facts["label"] == LABEL
    assert facts["track_record"]["resolved"] == 1
    assert facts["levels"][0]["id"] == "L1"


async def test_stored_forecasts_and_outcomes_cannot_be_changed(app_engine: AsyncEngine) -> None:
    provider, instrument, rows = await seed(HISTORY + 4)
    as_of = rows[HISTORY - 1].close_time
    clock = FixedClock(as_of + timedelta(minutes=1))
    forecasts = service(app_engine, StandInModel(), clock)
    stored = await forecasts.forecast(provider, instrument, Timeframe.H1, as_of, "manual")
    clock.advance(4 * 3600)
    await forecasts.resolve_due()
    connection = await asyncpg.connect(SUPERUSER_URL)
    try:
        for statement in (
            "UPDATE model_forecasts SET reason = 'study' WHERE id = $1",
            "DELETE FROM model_forecasts WHERE id = $1",
            "UPDATE model_forecast_outcomes SET realized_close = 1 WHERE forecast_id = $1",
        ):
            with pytest.raises(asyncpg.RestrictViolationError, match="immutable"):
                await connection.execute(statement, stored.id)
    finally:
        await connection.close()
