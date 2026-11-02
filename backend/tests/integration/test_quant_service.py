from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.conftest import make_settings
from tests.quant_data import START, candle
from trading_intel.database.engine import create_engine
from trading_intel.database.repositories.analysis import AnalysisRepository
from trading_intel.database.repositories.candles import CandleRepository
from trading_intel.database.repositories.reference import ReferenceRepository
from trading_intel.domain.base import DataOrigin
from trading_intel.domain.candles import ClosedCandle, Timeframe
from trading_intel.domain.patterns import DetectedPattern, Direction
from trading_intel.entrypoints.quant_worker import QuantService

pytestmark = pytest.mark.integration


async def seeded(engine: AsyncEngine, count: int) -> tuple[int, int, list[ClosedCandle]]:
    ingest = create_engine(make_settings().ingest_database_url)
    listed = await ReferenceRepository(ingest).provider_instruments("binance_spot")
    provider, instrument = listed[0].provider_id, listed[0].instrument.id
    candles = []
    previous = 100.0
    for index in range(count):
        close = 100.0 + (index % 17) * 2 + index * 0.1
        row = candle(index, previous, max(previous, close) + 1, min(previous, close) - 1, close)
        candles.append(
            row.model_copy(
                update={
                    "provider_id": provider,
                    "instrument_id": instrument,
                    "data_origin": DataOrigin.BACKFILL,
                }
            )
        )
        previous = close
    await CandleRepository(ingest).insert(candles)
    await ingest.dispose()
    return provider, instrument, candles


async def test_indicators_are_stored_for_the_closing_candle(app_engine: AsyncEngine) -> None:
    provider, instrument, candles = await seeded(app_engine, 120)
    analysis = AnalysisRepository(app_engine)
    service = QuantService(CandleRepository(app_engine), analysis, {"binance_spot": provider})
    as_of = candles[-1].close_time
    assert await service.process(provider, instrument, Timeframe.H1, as_of)
    stored = await analysis.latest_indicators(provider, instrument, Timeframe.H1, as_of)
    assert stored is not None
    close_time, values = stored
    assert close_time == as_of
    assert values["ema_20"] is not None
    assert values["ema_200"] is None  # Still warming up, and left empty.


async def test_processing_twice_changes_nothing(app_engine: AsyncEngine) -> None:
    provider, instrument, candles = await seeded(app_engine, 120)
    service = QuantService(
        CandleRepository(app_engine), AnalysisRepository(app_engine), {"binance_spot": provider}
    )
    as_of = candles[-1].close_time
    await service.process(provider, instrument, Timeframe.H1, as_of)
    async with app_engine.connect() as connection:
        first = (
            await connection.execute(text("SELECT count(*) FROM detected_patterns"))
        ).scalar_one()
    await service.process(provider, instrument, Timeframe.H1, as_of)
    async with app_engine.connect() as connection:
        second = (
            await connection.execute(text("SELECT count(*) FROM detected_patterns"))
        ).scalar_one()
    assert first == second
    assert first > 0


async def test_an_earlier_decision_time_sees_no_later_candle(app_engine: AsyncEngine) -> None:
    provider, instrument, candles = await seeded(app_engine, 120)
    analysis = AnalysisRepository(app_engine)
    service = QuantService(CandleRepository(app_engine), analysis, {"binance_spot": provider})
    earlier = candles[80].close_time
    await service.process(provider, instrument, Timeframe.H1, earlier)
    stored = await analysis.latest_indicators(provider, instrument, Timeframe.H1, earlier)
    assert stored is not None and stored[0] == earlier
    patterns = await analysis.recent_patterns(provider, instrument, Timeframe.H1, earlier, 500)
    assert all(p.detected_at <= earlier for p in patterns)


async def test_too_little_history_stores_nothing(app_engine: AsyncEngine) -> None:
    provider, instrument, candles = await seeded(app_engine, 5)
    analysis = AnalysisRepository(app_engine)
    service = QuantService(CandleRepository(app_engine), analysis, {"binance_spot": provider})
    assert not await service.process(provider, instrument, Timeframe.H1, candles[-1].close_time)


async def test_a_later_invalidation_updates_the_stored_pattern(app_engine: AsyncEngine) -> None:
    provider, instrument, _ = await seeded(app_engine, 1)
    analysis = AnalysisRepository(app_engine)
    pattern = DetectedPattern(
        pattern_type="fair_value_gap",
        direction=Direction.BULLISH,
        formed_at=START,
        detected_at=START + timedelta(hours=1),
        zone_low=78125.07,
        zone_high=78130.5,
        strength=40.0,
    )
    await analysis.store_patterns(provider, instrument, Timeframe.H1, [pattern])
    await analysis.store_patterns(
        provider, instrument, Timeframe.H1, [pattern.invalidated(START + timedelta(hours=5))]
    )
    [stored] = await analysis.recent_patterns(
        provider, instrument, Timeframe.H1, START + timedelta(days=1)
    )
    assert stored.validation_status == "invalidated"
    assert stored.zone_low == Decimal("78125.07")
