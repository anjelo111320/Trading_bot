from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.fakes import FakeProvider, make_candle
from trading_intel.core.clock import FixedClock
from trading_intel.database.repositories.candles import CandleRepository
from trading_intel.database.repositories.operations import (
    GapRepository,
    RuleRepository,
    RunRepository,
)
from trading_intel.database.repositories.reference import ReferenceRepository
from trading_intel.domain.candles import Timeframe
from trading_intel.domain.instruments import Instrument, InstrumentRules
from trading_intel.market_data.backfill import (
    FULL_PROFILE,
    GIB,
    TEST_PROFILE,
    BackfillRefusedError,
    BackfillService,
    BackfillTask,
    plan_tasks,
)
from trading_intel.market_data.gaps import GapRepairService
from trading_intel.market_data.instrument_rules import RuleSnapshotService
from trading_intel.market_data.reconcile import ReconcileService

pytestmark = pytest.mark.integration

START = datetime(2026, 1, 1, tzinfo=UTC)
PLENTY = 100 * GIB


async def setup(engine: AsyncEngine) -> tuple[int, Instrument]:
    listed = await ReferenceRepository(engine).provider_instruments("binance_spot")
    return listed[0].provider_id, listed[0].instrument


def service(provider: FakeProvider, engine: AsyncEngine, free: int = PLENTY) -> BackfillService:
    return BackfillService(
        provider,
        provider.provider_id,
        CandleRepository(engine),
        GapRepository(engine),
        RunRepository(engine),
        FixedClock(START + timedelta(days=1)),
        free_bytes=lambda: free,
    )


def minutes(instrument: Instrument, count: int) -> BackfillTask:
    return BackfillTask(instrument, Timeframe.M1, START, START + timedelta(minutes=count))


async def test_backfill_loads_every_candle_and_a_second_run_adds_nothing(
    ingest_engine: AsyncEngine,
) -> None:
    provider_id, instrument = await setup(ingest_engine)
    provider = FakeProvider(provider_id)
    first = await service(provider, ingest_engine).run([minutes(instrument, 120)], GIB)
    second = await service(provider, ingest_engine).run([minutes(instrument, 120)], GIB)
    assert first.rows_added == 120
    assert second.rows_added == 0
    assert provider.history_calls == 1  # The second run downloaded nothing.
    stored = await CandleRepository(ingest_engine).count(provider_id, instrument.id, Timeframe.M1)
    assert stored == 120


async def test_backfill_resumes_after_a_forced_stop_without_redownloading(
    ingest_engine: AsyncEngine,
) -> None:
    provider_id, instrument = await setup(ingest_engine)
    provider = FakeProvider(provider_id)
    provider.fail_after = 2500
    with pytest.raises(ConnectionError):
        await service(provider, ingest_engine).run([minutes(instrument, 3000)], GIB)
    stored = await CandleRepository(ingest_engine).count(provider_id, instrument.id, Timeframe.M1)
    assert stored == 2000  # Whole batches only.

    provider.fail_after = None
    provider.served = 0
    report = await service(provider, ingest_engine).run([minutes(instrument, 3000)], GIB)
    assert provider.served == 1000
    assert report.rows_added == 1000
    assert (
        await CandleRepository(ingest_engine).count(provider_id, instrument.id, Timeframe.M1)
        == 3000
    )


async def test_backfill_reaches_ranges_older_than_stored_data(ingest_engine: AsyncEngine) -> None:
    """Regression: resuming from the newest row skipped older ranges and invented gaps."""
    provider_id, instrument = await setup(ingest_engine)
    repository = CandleRepository(ingest_engine)
    await repository.insert(
        [make_candle(provider_id, instrument.id, Timeframe.M1, START + timedelta(days=30))]
    )
    report = await service(FakeProvider(provider_id), ingest_engine).run(
        [minutes(instrument, 60)], GIB
    )
    assert report.rows_added == 60
    assert report.gaps == 0
    assert await GapRepository(ingest_engine).list(provider_id=provider_id) == []


async def test_failed_run_is_marked_failed(ingest_engine: AsyncEngine) -> None:
    provider_id, instrument = await setup(ingest_engine)
    provider = FakeProvider(provider_id)
    provider.fail_after = 0
    with pytest.raises(ConnectionError):
        await service(provider, ingest_engine).run([minutes(instrument, 10)], GIB)
    async with ingest_engine.connect() as connection:
        status = (await connection.execute(text("SELECT status FROM ingest_runs"))).scalar_one()
    assert status == "failed"


async def test_provider_hole_is_recorded_and_never_filled(ingest_engine: AsyncEngine) -> None:
    provider_id, instrument = await setup(ingest_engine)
    hole = {START + timedelta(minutes=m) for m in (5, 6)}
    provider = FakeProvider(provider_id, holes=hole)
    report = await service(provider, ingest_engine).run([minutes(instrument, 10)], GIB)
    assert report.rows_added == 8
    assert report.rows_expected == 10
    [gap] = await GapRepository(ingest_engine).list(provider_id=provider_id)
    assert gap.state == "provider_missing"
    assert gap.gap_start == START + timedelta(minutes=5)
    assert gap.gap_end == START + timedelta(minutes=7)
    stored = await CandleRepository(ingest_engine).count(provider_id, instrument.id, Timeframe.M1)
    assert stored == report.rows_expected - 2


async def test_backfill_refuses_to_fill_the_disk(ingest_engine: AsyncEngine) -> None:
    provider_id, instrument = await setup(ingest_engine)
    provider = FakeProvider(provider_id)
    tight = service(provider, ingest_engine, free=2 * GIB + 1000)
    with pytest.raises(BackfillRefusedError, match="below"):
        await tight.run([minutes(instrument, 100)], 2 * GIB)
    assert provider.history_calls == 0


async def test_backfill_stops_if_free_space_falls_during_the_run(
    ingest_engine: AsyncEngine,
) -> None:
    provider_id, instrument = await setup(ingest_engine)
    readings = iter([PLENTY, PLENTY, GIB])
    backfill = BackfillService(
        FakeProvider(provider_id),
        provider_id,
        CandleRepository(ingest_engine),
        GapRepository(ingest_engine),
        RunRepository(ingest_engine),
        FixedClock(START),
        free_bytes=lambda: next(readings),
    )
    tasks = [minutes(instrument, 5), minutes(instrument, 5)]
    with pytest.raises(BackfillRefusedError, match="stopped with"):
        await backfill.run(tasks, 2 * GIB)


def test_profiles_match_the_decisions() -> None:
    assert TEST_PROFILE.window == timedelta(days=90)
    assert TEST_PROFILE.floor_bytes == 2 * GIB
    assert FULL_PROFILE.floor_bytes == 10 * GIB
    assert len(TEST_PROFILE.spot_timeframes) == 7
    assert Timeframe.M1 not in FULL_PROFILE.spot_timeframes


async def test_plan_ends_at_the_latest_closed_candle(ingest_engine: AsyncEngine) -> None:
    _, instrument = await setup(ingest_engine)
    now = datetime(2026, 11, 2, 10, 7, 30, tzinfo=UTC)
    tasks = plan_tasks([(instrument, datetime(2017, 8, 17, 4, tzinfo=UTC))], TEST_PROFILE, now)
    assert len(tasks) == 7
    one_hour = next(t for t in tasks if t.timeframe is Timeframe.H1)
    assert one_hour.end == datetime(2026, 11, 2, 10, tzinfo=UTC)
    assert one_hour.expected_rows == 90 * 24
    full = plan_tasks([(instrument, datetime(2017, 8, 17, 4, 7, tzinfo=UTC))], FULL_PROFILE, now)
    assert {t.timeframe for t in full} == {
        Timeframe.M15,
        Timeframe.M30,
        Timeframe.H1,
        Timeframe.H4,
        Timeframe.D1,
    }
    assert all(t.timeframe.is_aligned(t.start) for t in full)


async def test_ten_minute_outage_is_repaired_with_no_manual_action(
    ingest_engine: AsyncEngine,
) -> None:
    provider_id, instrument = await setup(ingest_engine)
    candles = CandleRepository(ingest_engine)
    await candles.insert(
        [
            make_candle(provider_id, instrument.id, Timeframe.M1, START + timedelta(minutes=m))
            for m in (*range(5), *range(15, 20))
        ]
    )
    gaps = GapRepository(ingest_engine)
    repair = GapRepairService(
        FakeProvider(provider_id), provider_id, candles, gaps, FixedClock(START)
    )
    result = await repair.repair(instrument, Timeframe.M1, START, START + timedelta(minutes=20))
    assert result.found == 1
    assert result.repaired == 1
    assert result.rows_recovered == 10
    assert await candles.count(provider_id, instrument.id, Timeframe.M1) == 20
    [gap] = await gaps.list(provider_id=provider_id)
    assert gap.state == "repaired"
    assert gap.resolved_at is not None


async def test_range_the_provider_cannot_supply_is_marked_as_missing(
    ingest_engine: AsyncEngine,
) -> None:
    provider_id, instrument = await setup(ingest_engine)
    provider = FakeProvider(provider_id, holes={START + timedelta(minutes=1)})
    gaps = GapRepository(ingest_engine)
    repair = GapRepairService(
        provider, provider_id, CandleRepository(ingest_engine), gaps, FixedClock(START)
    )
    result = await repair.repair(instrument, Timeframe.M1, START, START + timedelta(minutes=3))
    assert result.provider_missing == 1
    assert (await gaps.list(provider_id=provider_id))[0].state == "provider_missing"


async def test_sweep_recovers_a_candle_whose_closing_frame_was_lost(
    ingest_engine: AsyncEngine,
) -> None:
    provider_id, instrument = await setup(ingest_engine)
    candles = CandleRepository(ingest_engine)
    now = START + timedelta(minutes=10, seconds=35)
    await candles.insert(
        [
            make_candle(provider_id, instrument.id, Timeframe.M1, START + timedelta(minutes=m))
            for m in (5, 6, 7, 9)
        ]  # Minute 8 never arrived.
    )
    sweep = ReconcileService(FakeProvider(provider_id), provider_id, candles, FixedClock(now))
    result = await sweep.sweep(instrument, Timeframe.M1)
    assert result.checked == 5
    assert result.recovered == 1
    assert await candles.count(provider_id, instrument.id, Timeframe.M1) == 5


async def test_sweep_leaves_a_candle_that_has_only_just_closed_to_the_stream(
    ingest_engine: AsyncEngine,
) -> None:
    """Regression: the sweep raced the closing frame, which then counted as a duplicate."""
    provider_id, instrument = await setup(ingest_engine)
    candles = CandleRepository(ingest_engine)
    just_closed = START + timedelta(minutes=9)
    moment = just_closed + timedelta(minutes=1, seconds=29)
    sweep = ReconcileService(FakeProvider(provider_id), provider_id, candles, FixedClock(moment))
    await sweep.sweep(instrument, Timeframe.M1)
    stored = await candles.open_times(provider_id, instrument.id, Timeframe.M1, just_closed, moment)
    assert stored == []


async def test_value_mismatch_leaves_an_auditable_record(ingest_engine: AsyncEngine) -> None:
    provider_id, instrument = await setup(ingest_engine)
    candles = CandleRepository(ingest_engine)
    open_time = START + timedelta(minutes=9)
    await candles.insert([make_candle(provider_id, instrument.id, Timeframe.M1, open_time)])
    provider = FakeProvider(provider_id)
    provider.overrides[open_time] = make_candle(
        provider_id, instrument.id, Timeframe.M1, open_time, close=Decimal(106)
    )
    sweep = ReconcileService(
        provider, provider_id, candles, FixedClock(START + timedelta(minutes=10, seconds=35))
    )
    result = await sweep.sweep(instrument, Timeframe.M1)
    assert result.mismatched == 1
    async with ingest_engine.connect() as connection:
        reason = (
            await connection.execute(text("SELECT reason FROM market_candle_revisions"))
        ).scalar_one()
    assert "close" in reason
    [stored] = await candles.range(
        provider_id, instrument.id, Timeframe.M1, open_time, open_time + timedelta(minutes=1)
    )
    assert stored.close == Decimal(106)


async def test_minutes_aggregate_to_the_native_candle(ingest_engine: AsyncEngine) -> None:
    provider_id, instrument = await setup(ingest_engine)
    candles = CandleRepository(ingest_engine)
    parts = [
        make_candle(provider_id, instrument.id, Timeframe.M1, START + timedelta(minutes=m))
        for m in range(5)
    ]
    await candles.insert(parts)
    native = make_candle(provider_id, instrument.id, Timeframe.M5, START, volume=Decimal(25))
    await candles.insert([native])
    check = ReconcileService(FakeProvider(provider_id), provider_id, candles, FixedClock(START))
    assert await check.cross_check(instrument, Timeframe.M5, START) == []


async def test_aggregate_difference_is_reported(ingest_engine: AsyncEngine) -> None:
    provider_id, instrument = await setup(ingest_engine)
    candles = CandleRepository(ingest_engine)
    await candles.insert(
        [
            make_candle(provider_id, instrument.id, Timeframe.M1, START + timedelta(minutes=m))
            for m in range(5)
        ]
    )
    await candles.insert(
        [make_candle(provider_id, instrument.id, Timeframe.M5, START, volume=Decimal(99))]
    )
    check = ReconcileService(FakeProvider(provider_id), provider_id, candles, FixedClock(START))
    assert await check.cross_check(instrument, Timeframe.M5, START) == ["volume"]


def rules(tick: str) -> InstrumentRules:
    return InstrumentRules(
        status="TRADING",
        tick_size=Decimal(tick),
        lot_step=Decimal("0.001"),
        min_qty=Decimal("0.001"),
        max_qty=Decimal(1000),
        min_notional=Decimal(5),
        raw={"at": tick},
    )


async def test_rules_get_a_new_row_only_when_they_change(ingest_engine: AsyncEngine) -> None:
    provider_id, instrument = await setup(ingest_engine)
    provider = FakeProvider(provider_id)
    clock = FixedClock(START)
    repository = RuleRepository(ingest_engine)
    snapshots = RuleSnapshotService(provider, provider_id, repository, clock)

    provider.rules = rules("0.01")
    assert await snapshots.refresh([instrument]) == 1
    clock.advance(21600)
    assert await snapshots.refresh([instrument]) == 0

    clock.advance(21600)
    changed_at = clock.now()
    provider.rules = rules("0.10")
    assert await snapshots.refresh([instrument]) == 1

    earlier = await repository.as_of(provider_id, instrument.id, changed_at - timedelta(seconds=1))
    later = await repository.as_of(provider_id, instrument.id, changed_at)
    assert earlier is not None and earlier.tick_size == Decimal("0.01")
    assert later is not None and later.tick_size == Decimal("0.10")
