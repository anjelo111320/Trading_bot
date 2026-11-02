"""Signal to paper position to outcome, on real PostgreSQL."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from typing import Any

import asyncpg
import pytest
from sqlalchemy import text

from tests.conftest import make_settings
from tests.integration.support import SUPERUSER_URL
from tests.quant_data import candle
from trading_intel.core.clock import FixedClock
from trading_intel.database.engine import create_engine
from trading_intel.database.repositories.accounts import UserRepository
from trading_intel.database.repositories.candles import CandleRepository
from trading_intel.database.repositories.operations import (
    GapRepository,
    MarketRepository,
    RuleRepository,
    SnapshotRepository,
    SnapshotRow,
)
from trading_intel.database.repositories.paper import PaperRepository
from trading_intel.database.repositories.reference import ReferenceRepository
from trading_intel.database.repositories.signals import Account, SignalRepository
from trading_intel.domain.base import DataOrigin
from trading_intel.domain.candles import ClosedCandle, Timeframe
from trading_intel.domain.instruments import Instrument, InstrumentRules
from trading_intel.domain.signals import EntryType, Side
from trading_intel.paper_trading.service import PaperService
from trading_intel.risk_management.models import TradeProposal
from trading_intel.trade_signals.service import SignalService

pytestmark = pytest.mark.integration

EMAIL = "owner@example.test"
NOW = datetime(2026, 11, 3, 1, tzinfo=UTC)  # After the fee schedule took effect.


class World:
    provider_id: int
    instrument: Instrument
    account: Account
    clock: FixedClock
    signals: SignalService
    paper: PaperService
    paper_repository: PaperRepository
    candles: CandleRepository
    records: SignalRepository


@pytest.fixture
async def world(clean_database: None) -> AsyncIterator[World]:
    settings = make_settings()
    app = create_engine(settings.database_url)
    ingest = create_engine(settings.ingest_database_url)
    state = World()
    await UserRepository(app).create_owner(EMAIL, "hash")
    listed = await ReferenceRepository(app).provider_instruments("binance_usdm")
    state.provider_id = listed[0].provider_id
    state.instrument = listed[0].instrument
    state.clock = FixedClock(NOW)
    state.candles = CandleRepository(ingest)
    await RuleRepository(ingest).replace_current(
        state.provider_id,
        state.instrument.id,
        InstrumentRules(
            status="TRADING",
            tick_size=D("0.01"),
            lot_step=D("0.001"),
            min_qty=D("0.001"),
            max_qty=D(100000),
            min_notional=D(5),
            maintenance_margin_fraction=D("0.025"),
            raw={},
        ),
        NOW - timedelta(days=1),
    )
    await SnapshotRepository(ingest).upsert(
        SnapshotRow(
            provider_id=state.provider_id,
            instrument_id=state.instrument.id,
            minute_start=NOW - timedelta(seconds=5),
            best_bid=D("99.99"),
            best_ask=D("100.01"),
            spread_min=None,
            spread_mean=None,
            spread_max=None,
            spread_last=None,
            sample_count=1,
            crossed_book_count=0,
            data_origin=DataOrigin.LIVE,
            received_at=NOW,
        )
    )
    await state.candles.insert(
        [bar(state, -30 + minute, "100", "100.2", "99.8", "100") for minute in range(30)]
    )
    state.records = SignalRepository(app)
    state.paper_repository = PaperRepository(app)
    market = MarketRepository(app)
    state.signals = SignalService(
        CandleRepository(app),
        SnapshotRepository(app),
        market,
        GapRepository(app),
        RuleRepository(app),
        state.records,
        state.paper_repository,
        state.clock,
    )
    state.paper = PaperService(CandleRepository(app), market, state.paper_repository, state.clock)
    account = await state.records.ensure_account(EMAIL)
    assert account is not None
    state.account = account
    yield state
    await app.dispose()
    await ingest.dispose()


def bar(
    world: World,
    minute: int,
    open_: str,
    high: str,
    low: str,
    close: str,
    origin: DataOrigin = DataOrigin.LIVE,
) -> ClosedCandle:
    base = candle(0, float(open_), float(high), float(low), float(close), 5000.0, Timeframe.M1)
    at = NOW + timedelta(minutes=minute)
    return base.model_copy(
        update={
            "provider_id": world.provider_id,
            "instrument_id": world.instrument.id,
            "open_time": at,
            "close_time": Timeframe.M1.close_time(at),
            "data_origin": origin,
        }
    )


def proposal(**overrides: Any) -> TradeProposal:
    values: dict[str, Any] = {
        "side": Side.LONG,
        "entry_type": EntryType.MARKET,
        "entry": D("100.00"),
        "stop": D("98.00"),
        "targets": (D("104.00"), D("106.00"), D("108.00")),
        "invalidation_conditions": ("close below 98.00",),
    }
    return TradeProposal(**{**values, **overrides})


async def approve(world: World, **overrides: Any) -> Any:
    return await world.signals._assess(
        world.provider_id,
        world.instrument,
        NOW,
        world.account,
        await RuleRepository(world.signals._rules._engine).current(
            world.provider_id, world.instrument.id
        ),
        proposal(**overrides),
        D(1),
        ("BOS with both higher timeframes up",),
    )


async def rows(sql: str) -> list[Any]:
    connection = await asyncpg.connect(SUPERUSER_URL)
    result = await connection.fetch(sql)
    await connection.close()
    return list(result)


async def test_an_approved_signal_creates_every_record(world: World) -> None:
    outcome = await approve(world)
    assert outcome.approved, outcome.reasons
    [recommendation] = await rows("SELECT action, news_alignment FROM trade_recommendations")
    assert recommendation["action"] == "BUY"
    assert recommendation["news_alignment"] == "unavailable"
    assert len(await rows("SELECT * FROM trade_targets")) == 3
    [risk] = await rows("SELECT decision, quantity FROM risk_assessments")
    assert risk["decision"] == "APPROVED"
    states = [r["to_state"] for r in await rows("SELECT to_state FROM signal_events ORDER BY id")]
    assert states == ["CANDIDATE", "VALIDATED", "ACTIVE"]
    assert len(await rows("SELECT * FROM paper_positions WHERE status = 'pending_entry'")) == 1
    assert len(await rows("SELECT * FROM alerts WHERE channel = 'in_app'")) == 1


async def test_a_rejected_signal_is_stored_with_its_reasons_and_opens_nothing(world: World) -> None:
    outcome = await approve(world, targets=(D("104.00"),))
    assert not outcome.approved
    assert "RR_BELOW_MIN" in outcome.reasons
    [risk] = await rows("SELECT decision, rejection_codes FROM risk_assessments")
    assert risk["decision"] == "REJECTED"
    assert "RR_BELOW_MIN" in risk["rejection_codes"]
    assert await rows("SELECT * FROM paper_positions") == []
    assert await rows("SELECT * FROM alerts") == []


async def test_the_same_trade_is_refused_while_one_is_active(world: World) -> None:
    assert (await approve(world)).approved
    second = await approve(world)
    assert not second.approved
    assert "DUPLICATE_ACTIVE_SIGNAL" in second.reasons


async def test_a_winning_trade_runs_to_its_outcome(world: World) -> None:
    await approve(world)
    await world.candles.insert(
        [
            bar(world, 1, "100", "100.5", "99.5", "100.2"),
            bar(world, 2, "100.2", "104.5", "100", "104"),
            bar(world, 3, "104", "108.5", "103.9", "108"),
        ]
    )
    world.clock.advance(300)
    result = await world.paper.sync(world.provider_id, world.instrument.id)
    assert result.new_fills == 4
    kinds = [
        r["kind"]
        for r in await rows("SELECT kind FROM paper_executions ORDER BY executed_at, kind")
    ]
    assert sorted(kinds) == ["entry", "tp1", "tp2", "tp3"]
    [outcome] = await rows("SELECT outcome, net_pnl FROM trade_outcomes")
    assert outcome["outcome"] == "WIN"
    assert outcome["net_pnl"] > 0
    [state] = await rows("SELECT state FROM signal_current_state")
    assert state["state"] == "TP3_HIT"


async def test_a_replay_never_fills_twice(world: World) -> None:
    await approve(world)
    await world.candles.insert([bar(world, 1, "100", "100.5", "99.5", "100.2")])
    world.clock.advance(120)
    first = await world.paper.sync(world.provider_id, world.instrument.id)
    second = await world.paper.sync(world.provider_id, world.instrument.id)
    assert first.new_fills == 1
    assert second.new_fills == 0
    assert len(await rows("SELECT * FROM paper_executions")) == 1


async def test_a_stop_loses_and_updates_equity(world: World) -> None:
    await approve(world)
    await world.candles.insert(
        [
            bar(world, 1, "100", "100.5", "99.5", "100"),
            bar(world, 2, "100", "100", "97", "97.5"),
        ]
    )
    world.clock.advance(240)
    await world.paper.sync(world.provider_id, world.instrument.id)
    [outcome] = await rows("SELECT outcome, net_pnl FROM trade_outcomes")
    assert outcome["outcome"] == "LOSS"
    state = await world.paper_repository.account_state(
        world.account.id, world.account.starting_balance, NOW - timedelta(days=1)
    )
    assert state.equity == D(10000) + outcome["net_pnl"]
    assert state.equity < D(10000)
    assert state.open_positions == 0


async def test_an_open_loss_counts_against_equity(world: World) -> None:
    """Regression: equity once ignored open positions, weakening the daily loss limit."""
    await approve(world)
    await world.candles.insert([bar(world, 1, "100", "100.5", "99.5", "100")])
    world.clock.advance(120)
    await world.paper.sync(world.provider_id, world.instrument.id)
    ingest = create_engine(make_settings().ingest_database_url)
    await SnapshotRepository(ingest).upsert(
        SnapshotRow(
            provider_id=world.provider_id,
            instrument_id=world.instrument.id,
            minute_start=NOW + timedelta(minutes=2),
            best_bid=D("98.99"),
            best_ask=D("99.01"),
            spread_min=None,
            spread_mean=None,
            spread_max=None,
            spread_last=None,
            sample_count=1,
            crossed_book_count=0,
            data_origin=DataOrigin.LIVE,
            received_at=NOW,
        )
    )
    await ingest.dispose()
    state = await world.paper_repository.account_state(
        world.account.id, world.account.starting_balance, NOW - timedelta(days=1)
    )
    assert state.equity < world.account.starting_balance
    assert state.day_start_equity == world.account.starting_balance


async def test_fills_from_repaired_candles_are_marked_reconstructed(world: World) -> None:
    await approve(world)
    await world.candles.insert(
        [bar(world, 1, "100", "100.5", "99.5", "100.2", origin=DataOrigin.BACKFILL)]
    )
    world.clock.advance(120)
    await world.paper.sync(world.provider_id, world.instrument.id)
    [fill] = await rows("SELECT reconstructed, simulated FROM paper_executions")
    assert fill["reconstructed"] is True
    assert fill["simulated"] is True


async def test_an_unfilled_trade_is_excluded_from_win_rate(world: World) -> None:
    await approve(
        world,
        entry_type=EntryType.LIMIT,
        entry=D("95.00"),
        stop=D("93.00"),
        targets=(D("103.00"),),
    )
    await world.candles.insert(
        [bar(world, minute, "100", "100.5", "99.5", "100") for minute in range(1, 130)]
    )
    world.clock.advance(3 * 3600)
    await world.paper.sync(world.provider_id, world.instrument.id)
    [outcome] = await rows("SELECT outcome, counts_for_win_rate FROM trade_outcomes")
    assert outcome["outcome"] == "EXPIRED"
    assert outcome["counts_for_win_rate"] is False


async def test_recommendations_cannot_be_edited_afterwards(world: World) -> None:
    await approve(world)
    with pytest.raises(asyncpg.RestrictViolationError):
        await rows("UPDATE trade_recommendations SET stop_loss = 1")
    with pytest.raises(asyncpg.RestrictViolationError):
        await rows("DELETE FROM risk_assessments")


async def test_a_second_active_copy_is_blocked_by_the_database_too(world: World) -> None:
    assert (await approve(world)).approved
    second = await approve(world)  # Refused by the engine, so it has no active state yet.
    with pytest.raises(asyncpg.UniqueViolationError):
        await rows(
            "INSERT INTO signal_current_state (recommendation_id, account_id, dedupe_key, state) "
            f"SELECT '{second.recommendation_id}', account_id, dedupe_key, state "
            "FROM signal_current_state"
        )


async def test_a_live_account_is_impossible(world: World) -> None:
    with pytest.raises(asyncpg.CheckViolationError):
        await rows("UPDATE trading_accounts SET mode = 'live'")


async def test_a_real_execution_flag_is_impossible(world: World) -> None:
    await approve(world)
    await world.candles.insert([bar(world, 1, "100", "100.5", "99.5", "100.2")])
    world.clock.advance(120)
    await world.paper.sync(world.provider_id, world.instrument.id)
    async with create_engine(make_settings().migration_database_url).connect() as connection:
        columns = (
            await connection.execute(
                text(
                    "SELECT count(*) FROM information_schema.check_constraints "
                    "WHERE check_clause LIKE '%simulated%'"
                )
            )
        ).scalar_one()
    assert columns >= 1
