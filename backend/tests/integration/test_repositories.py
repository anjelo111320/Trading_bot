from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.support import SUPERUSER_URL
from tests.unit.test_candles import candle_fields
from trading_intel.database.repositories.candles import CandleRepository, differences
from trading_intel.database.repositories.operations import (
    GapRepository,
    RuleRepository,
    RunRepository,
    SnapshotRepository,
    SnapshotRow,
)
from trading_intel.database.repositories.reference import ReferenceRepository
from trading_intel.domain.base import DataOrigin
from trading_intel.domain.candles import ClosedCandle, Timeframe
from trading_intel.domain.instruments import InstrumentRules

pytestmark = pytest.mark.integration

START = datetime(2026, 1, 1, tzinfo=UTC)


async def ids(engine: AsyncEngine) -> tuple[int, int]:
    reference = ReferenceRepository(engine)
    instruments = await reference.provider_instruments("binance_spot")
    return instruments[0].provider_id, instruments[0].instrument.id


def candle(provider: int, instrument: int, minute: int = 0, **overrides: Any) -> ClosedCandle:
    open_time = START + timedelta(minutes=minute)
    return ClosedCandle(
        **candle_fields(
            provider_id=provider, instrument_id=instrument, open_time=open_time, **overrides
        )
    )


def rules(tick: str = "0.01") -> InstrumentRules:
    return InstrumentRules(
        status="TRADING",
        tick_size=Decimal(tick),
        lot_step=Decimal("0.00001"),
        min_qty=Decimal("0.00001"),
        max_qty=Decimal(9000),
        min_notional=Decimal(5),
        raw={"filters": []},
    )


async def test_seeded_reference_data(ingest_engine: AsyncEngine) -> None:
    reference = ReferenceRepository(ingest_engine)
    spot = await reference.provider_instruments("binance_spot")
    usdm = await reference.provider_instruments("binance_usdm")
    assert [p.instrument.symbol for p in spot] == ["BTCUSDT", "ETHUSDT"]
    assert {p.instrument.instrument_type.value for p in usdm} == {"linear_perpetual"}
    assert spot[0].instrument.id != usdm[0].instrument.id


async def test_inserting_the_same_candle_twice_leaves_one_row(ingest_engine: AsyncEngine) -> None:
    provider, instrument = await ids(ingest_engine)
    repository = CandleRepository(ingest_engine)
    first = candle(provider, instrument)
    assert await repository.insert([first]) == 1
    assert await repository.insert([first]) == 0
    assert await repository.count(provider, instrument, Timeframe.M1) == 1


async def test_stored_candle_round_trips_exactly(ingest_engine: AsyncEngine) -> None:
    provider, instrument = await ids(ingest_engine)
    repository = CandleRepository(ingest_engine)
    original = candle(provider, instrument, close=Decimal("105.123456789012345678"))
    await repository.insert([original])
    [stored] = await repository.page(provider, instrument, Timeframe.M1, 10)
    assert stored.close == Decimal("105.123456789012345678")
    assert stored.open_time.tzinfo is not None
    assert differences(stored, original) == []


async def test_invalid_ohlc_is_rejected_by_the_database_too(ingest_engine: AsyncEngine) -> None:
    provider, instrument = await ids(ingest_engine)
    with pytest.raises(DBAPIError, match="market_candles_ohlc_high"):
        async with ingest_engine.begin() as connection:
            await connection.execute(
                text(
                    """INSERT INTO market_candles (provider_id, instrument_id, timeframe, open_time,
                         close_time, open, high, low, close, volume, quote_volume, trade_count,
                         provider_open_time_raw, data_origin, received_at)
                       VALUES (:p, :i, '1m', now(), now() + interval '1 minute', 100, 99, 90, 95, 1,
                         1, 1, 1, 'backfill', now())"""
                ),
                {"p": provider, "i": instrument},
            )


async def test_api_role_cannot_write_candles(app_engine: AsyncEngine) -> None:
    provider, instrument = await ids(app_engine)
    with pytest.raises(DBAPIError, match="permission denied"):
        await CandleRepository(app_engine).insert([candle(provider, instrument)])


async def test_ingest_role_cannot_read_users(ingest_engine: AsyncEngine) -> None:
    with pytest.raises(DBAPIError, match="permission denied"):
        async with ingest_engine.connect() as connection:
            await connection.execute(text("SELECT * FROM users"))


async def test_page_walks_backwards_without_overlap(ingest_engine: AsyncEngine) -> None:
    provider, instrument = await ids(ingest_engine)
    repository = CandleRepository(ingest_engine)
    await repository.insert([candle(provider, instrument, m) for m in range(5)])
    newest = await repository.page(provider, instrument, Timeframe.M1, 2)
    older = await repository.page(provider, instrument, Timeframe.M1, 2, before=newest[0].open_time)
    assert [c.open_time.minute for c in newest] == [3, 4]
    assert [c.open_time.minute for c in older] == [1, 2]


async def test_correction_keeps_an_auditable_record(ingest_engine: AsyncEngine) -> None:
    provider, instrument = await ids(ingest_engine)
    repository = CandleRepository(ingest_engine)
    stored = candle(provider, instrument)
    corrected = candle(provider, instrument, close=Decimal(106))
    await repository.insert([stored])
    await repository.replace_with_revision(stored, corrected, "reconcile mismatch")
    [now_stored] = await repository.page(provider, instrument, Timeframe.M1, 1)
    assert now_stored.close == Decimal(106)
    connection = await asyncpg.connect(SUPERUSER_URL)
    revision = await connection.fetchrow(
        "SELECT previous, replacement FROM market_candle_revisions"
    )
    await connection.close()
    assert revision is not None
    assert '"close": "105"' in revision["previous"]
    assert '"close": "106"' in revision["replacement"]


async def test_analysis_read_excludes_synthetic_and_future_candles(
    ingest_engine: AsyncEngine,
) -> None:
    reference = ReferenceRepository(ingest_engine)
    synthetic = (await reference.provider_instruments("synthetic"))[0]
    repository = CandleRepository(ingest_engine)
    fake = candle(synthetic.provider_id, synthetic.instrument.id, data_origin=DataOrigin.SYNTHETIC)
    await repository.insert([fake])
    assert (
        await repository.for_analysis(
            synthetic.provider_id,
            synthetic.instrument.id,
            Timeframe.M1,
            START + timedelta(days=1),
            10,
        )
        == []
    )

    provider, instrument = await ids(ingest_engine)
    await repository.insert([candle(provider, instrument, m) for m in range(3)])
    visible = await repository.for_analysis(
        provider, instrument, Timeframe.M1, START + timedelta(minutes=2), 10
    )
    assert [c.open_time.minute for c in visible] == [0, 1]


async def test_gap_is_recorded_once_and_can_be_resolved(ingest_engine: AsyncEngine) -> None:
    provider, instrument = await ids(ingest_engine)
    gaps = GapRepository(ingest_engine)
    end = START + timedelta(minutes=5)
    await gaps.record(provider, instrument, Timeframe.M1, START, end, "ingest_failure")
    await gaps.record(provider, instrument, Timeframe.M1, START, end, "ingest_failure")
    assert len(await gaps.list(states=("detected",))) == 1
    await gaps.set_state(provider, instrument, Timeframe.M1, START, "repaired", end)
    assert await gaps.list(states=("detected",)) == []
    assert (await gaps.list(provider_id=provider))[0].state == "repaired"


async def test_rule_history_answers_as_of_queries(ingest_engine: AsyncEngine) -> None:
    provider, instrument = await ids(ingest_engine)
    repository = RuleRepository(ingest_engine)
    await repository.replace_current(provider, instrument, rules("0.01"), START)
    changed = START + timedelta(days=1)
    await repository.replace_current(provider, instrument, rules("0.10"), changed)

    before = await repository.as_of(provider, instrument, START + timedelta(hours=1))
    after = await repository.as_of(provider, instrument, changed)
    current = await repository.current(provider, instrument)
    assert before is not None and before.tick_size == Decimal("0.01")
    assert after is not None and after.tick_size == Decimal("0.10")
    assert current is not None and current.tick_size == Decimal("0.10")
    assert await repository.as_of(provider, instrument, START - timedelta(days=1)) is None


async def test_snapshot_columns_merge_without_erasing_earlier_values(
    ingest_engine: AsyncEngine,
) -> None:
    provider, instrument = await ids(ingest_engine)
    repository = SnapshotRepository(ingest_engine)
    base = {
        "provider_id": provider,
        "instrument_id": instrument,
        "minute_start": START,
        "best_bid": None,
        "best_ask": None,
        "spread_min": None,
        "spread_mean": None,
        "spread_max": None,
        "spread_last": None,
        "sample_count": 0,
        "crossed_book_count": 0,
        "data_origin": DataOrigin.LIVE,
        "received_at": START,
    }
    await repository.upsert(SnapshotRow(**{**base, "spread_mean": Decimal(1), "sample_count": 5}))
    await repository.upsert(SnapshotRow(**base, mark_price=Decimal(100)))
    assert (
        await repository.spread_minutes(provider, instrument, START, START + timedelta(minutes=1))
        == 1
    )
    connection = await asyncpg.connect(SUPERUSER_URL)
    row = await connection.fetchrow("SELECT spread_mean, mark_price FROM market_snapshots")
    await connection.close()
    assert row is not None
    assert row["spread_mean"] == Decimal(1)
    assert row["mark_price"] == Decimal(100)


async def test_run_records_outcome(ingest_engine: AsyncEngine) -> None:
    provider, _ = await ids(ingest_engine)
    runs = RunRepository(ingest_engine)
    run_id = await runs.start(provider, "backfill", "abc")
    await runs.finish(run_id, "succeeded", {"rows": 3})
    async with ingest_engine.connect() as connection:
        status = (
            await connection.execute(
                text("SELECT status FROM ingest_runs WHERE id = :id"), {"id": run_id}
            )
        ).scalar_one()
    assert status == "succeeded"
