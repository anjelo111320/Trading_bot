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
from trading_intel.api.routers.trading import _trade
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
from trading_intel.database.repositories.signals import (
    DEMO_ACCOUNT,
    DEMO_BALANCE,
    PORTFOLIO_ACCOUNT,
    PORTFOLIO_BALANCE,
    Account,
    SignalRepository,
)
from trading_intel.domain.base import DataOrigin
from trading_intel.domain.candles import ClosedCandle, Timeframe
from trading_intel.domain.events import plain
from trading_intel.domain.instruments import Instrument, InstrumentRules
from trading_intel.domain.signals import Action, EntryType, Side
from trading_intel.paper_trading.service import PaperService
from trading_intel.risk_management.models import TradeProposal
from trading_intel.trade_signals.baseline import BaselineDecision
from trading_intel.trade_signals.portfolio import PLAN_PROFILE
from trading_intel.trade_signals.service import Setup, SignalService, StrategyIdentity

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


TREND = StrategyIdentity("daily_trend", 1, {"test": True})


def day(world: World, days_before: int, low: str, high: str) -> ClosedCandle:
    """A daily candle that closed before NOW, rising as `days_before` falls."""
    at = Timeframe.D1.floor(NOW) - timedelta(days=days_before)
    base = candle(0, float(low), float(high), float(low), float(high), 1000.0, Timeframe.D1)
    return base.model_copy(
        update={
            "provider_id": world.provider_id,
            "instrument_id": world.instrument.id,
            "open_time": at,
            "close_time": Timeframe.D1.close_time(at),
            "data_origin": DataOrigin.LIVE,
        }
    )


async def open_trend(world: World) -> Any:
    rules = await RuleRepository(world.signals._rules._engine).current(
        world.provider_id, world.instrument.id
    )
    return await world.signals._assess(
        world.provider_id,
        world.instrument,
        NOW,
        world.account,
        rules,
        proposal(stop=D("50.00"), targets=(D("1000.00"),)),
        D(1),
        ("close beyond the 20-day range",),
        strategy=TREND,
        timeframe=Timeframe.D1,
    )


async def test_a_trailed_stop_takes_effect_from_the_next_candle(world: World) -> None:
    """D039: a stop decided at a close applies from the next candle, never to that one."""
    await approve(world)
    [trade] = await world.paper_repository.active(world.provider_id, world.instrument.id)
    after = Timeframe.M1.close_time(NOW + timedelta(minutes=1))
    assert await world.paper_repository.record_stop_move(
        trade.position_id, after, D("99.60"), "test"
    )
    assert not await world.paper_repository.record_stop_move(
        trade.position_id, after, D("99.70"), "test"
    ), "a move is recorded once"
    await world.candles.insert(
        [
            bar(world, 1, "100", "100.5", "99.5", "100.2"),  # Before the move: no stop.
            bar(world, 2, "100.2", "100.3", "99.5", "99.8"),  # After it: stopped at 99.60.
        ]
    )
    world.clock.advance(240)
    await world.paper.sync(world.provider_id, world.instrument.id)
    fills = await rows("SELECT kind, executed_at FROM paper_executions ORDER BY executed_at")
    assert [f["kind"] for f in fills] == ["entry", "stop"]
    assert fills[1]["executed_at"] == Timeframe.M1.close_time(NOW + timedelta(minutes=2))
    [outcome] = await rows("SELECT outcome FROM trade_outcomes")
    assert outcome["outcome"] == "LOSS"


async def test_each_strategy_holds_one_position_per_coin(world: World) -> None:
    assert (await open_trend(world)).approved
    rules = await RuleRepository(world.signals._rules._engine).current(
        world.provider_id, world.instrument.id
    )
    assert rules is not None
    decision = BaselineDecision(
        Action.BUY, NOW, ("again",), proposal=proposal(entry=D("100.50")), setup_atr=D(1)
    )
    again = await world.signals._submit(
        world.provider_id,
        world.instrument,
        NOW,
        world.account,
        rules,
        decision,
        TREND,
        Timeframe.D1,
    )
    assert not again.approved and again.reasons == ("a position from this strategy is open",)
    other = await world.signals._submit(
        world.provider_id,
        world.instrument,
        NOW,
        world.account,
        rules,
        decision,
        StrategyIdentity("pattern_breakout", 1, {"test": True}),
        Timeframe.H1,
    )
    assert other.recommendation_id is not None, "another strategy still reaches the risk engine"


async def test_the_trend_stop_trails_the_10_day_low_once_per_close(world: World) -> None:
    assert (await open_trend(world)).approved
    await world.candles.insert(
        [day(world, n, str(100 + (30 - n)), str(102 + (30 - n))) for n in range(30, 0, -1)]
    )
    last_close = Timeframe.D1.close_time(Timeframe.D1.floor(NOW) - timedelta(days=1))
    assert await world.signals.trail_stops(world.provider_id, world.instrument, last_close) == 1
    [trade] = await world.paper_repository.active(world.provider_id, world.instrument.id)
    # The lowest low of the last 10 days: the candle 10 days back opened at 120.
    assert trade.stop_moves == ((last_close, D("120.00")),)
    assert await world.signals.trail_stops(world.provider_id, world.instrument, last_close) == 0


async def test_a_book_from_the_minute_just_finished_counts_as_fresh(world: World) -> None:
    """Regression: books are stored per finished minute, so their start is always over a
    minute old, and every live signal was refused as stale (2026-11-07)."""
    world.clock.advance(65)  # One minute and five seconds after NOW.
    await SnapshotRepository(world.candles._engine).upsert(
        SnapshotRow(
            provider_id=world.provider_id,
            instrument_id=world.instrument.id,
            minute_start=NOW,  # The minute that has just finished.
            best_bid=D("99.99"),
            best_ask=D("100.01"),
            spread_min=None,
            spread_mean=None,
            spread_max=None,
            spread_last=None,
            sample_count=1,
            crossed_book_count=0,
            data_origin=DataOrigin.LIVE,
            received_at=NOW + timedelta(seconds=61),
        )
    )
    outcome = await approve(world)
    assert outcome.approved, outcome.reasons


async def demo_trade(world: World, **overrides: Any) -> tuple[Account, Any]:
    """The demo bot's signal ten seconds into the minute, through the same risk engine."""
    demo = await world.records.ensure_account(EMAIL, DEMO_ACCOUNT, DEMO_BALANCE)
    assert demo is not None
    world.clock.advance(10)
    outcome = await world.signals._assess(
        world.provider_id,
        world.instrument,
        NOW,
        demo,
        await RuleRepository(world.signals._rules._engine).current(
            world.provider_id, world.instrument.id
        ),
        proposal(**overrides),
        D(1),
        ("BOS with both higher timeframes up",),
        instant=True,
    )
    return demo, outcome


async def test_the_demo_bot_has_its_own_100_usdt_account(world: World) -> None:
    demo = await world.records.ensure_account(EMAIL, DEMO_ACCOUNT, DEMO_BALANCE)
    assert demo is not None
    assert demo.id != world.account.id
    assert demo.starting_balance == D(100)
    assert demo.profile.max_risk_fraction == D("0.01")
    again = await world.records.ensure_account(EMAIL, DEMO_ACCOUNT, DEMO_BALANCE)
    assert again is not None and again.id == demo.id


async def test_the_demo_bot_is_sized_and_filled_at_the_live_price(world: World) -> None:
    """D044: the entry is the live mid rounded against the trade, not the 15M close."""
    demo, outcome = await demo_trade(world, entry=D("99.50"))
    assert outcome.approved, outcome.reasons
    [plan] = await rows(
        "SELECT r.entry_price, a.entry_fill_est, a.max_account_risk FROM trade_recommendations r "
        "JOIN risk_assessments a ON a.recommendation_id = r.id"
    )
    assert plan["entry_price"] == D("100.00")  # The mid of 99.99 and 100.01.
    assert plan["max_account_risk"] <= D(1)  # 1% of 100 USDT.
    await world.candles.insert(
        [
            bar(world, 0, "100", "104.5", "99.5", "104"),
            bar(world, 1, "104", "104.5", "103.5", "104"),
        ]
    )
    world.clock.advance(120)
    await world.paper.sync(world.provider_id, world.instrument.id)
    fills = await rows("SELECT kind, fill_price, executed_at FROM paper_executions ORDER BY id")
    assert [fill["kind"] for fill in fills] == ["entry", "tp1"]
    assert fills[0]["executed_at"] == NOW + timedelta(seconds=10)
    assert fills[0]["fill_price"] == plan["entry_fill_est"]
    assert fills[1]["executed_at"] == Timeframe.M1.close_time(NOW + timedelta(minutes=1))
    [view] = [_trade(row) for row in await world.paper_repository.trades(demo.id, None)]
    assert view.simulated is True
    assert [fill.kind for fill in view.fills] == ["entry", "tp1"]
    assert view.fills[0].at == NOW + timedelta(seconds=10)
    assert view.fills[0].price == plain(plan["entry_fill_est"])
    assert view.status == "open"
    assert [D(price) for price in view.targets] == [D(104), D(106), D(108)]


async def test_accounts_report_only_their_own_trades(world: World) -> None:
    assert (await approve(world)).approved
    demo, outcome = await demo_trade(world, side=Side.SHORT, stop=D("102.00"),
                                     targets=(D("96.00"), D("94.00"), D("92.00")),
                                     invalidation_conditions=("close above 102.00",))  # fmt: skip
    assert outcome.approved, outcome.reasons
    paper = world.paper_repository
    assert [row["side"] for row in await paper.positions(world.account.id)] == ["LONG"]
    assert [row["side"] for row in await paper.positions(demo.id)] == ["SHORT"]
    assert [row["action"] for row in await world.records.recent(demo.id)] == ["SELL"]
    [trade] = await paper.trades(demo.id, world.instrument.id)
    assert trade["strategy"] == "trend_break_baseline"
    assert [D(price) for price in trade["targets"]] == [D(96), D(94), D(92)]
    assert trade["fills"] is None
    assert await paper.trades(demo.id, world.instrument.id + 1000) == []
    assert (await paper.performance(demo.id))["resolved"] == 0


PATTERN = StrategyIdentity("pattern_breakout", 1, {"test": True})
BASELINE = StrategyIdentity("trend_break_baseline", 1, {"test": True})


async def plan_account(world: World) -> Account:
    account = await world.records.ensure_account(
        EMAIL, PORTFOLIO_ACCOUNT, PORTFOLIO_BALANCE, PLAN_PROFILE
    )
    assert account is not None
    return account


async def plan_setup(world: World, identity: StrategyIdentity, stop: str) -> Setup:
    rules = await RuleRepository(world.signals._rules._engine).current(
        world.provider_id, world.instrument.id
    )
    assert rules is not None
    decision = BaselineDecision(
        Action.BUY, NOW, ("test setup",), proposal=proposal(stop=D(stop)), setup_atr=D(1)
    )
    timeframe = {"daily_trend": Timeframe.D1, "pattern_breakout": Timeframe.H1}
    return Setup(
        world.instrument, rules, decision, identity, timeframe.get(identity.name, Timeframe.M15)
    )


async def plan_rows() -> list[Any]:
    return await rows(
        "SELECT c.name, a.decision, a.rejection_codes, a.max_account_risk, a.notional, "
        "a.inputs->>'risk_share' AS share, a.inputs->>'evidence_share' AS evidence "
        "FROM risk_assessments a JOIN trade_recommendations r ON r.id = a.recommendation_id "
        "JOIN strategy_configurations c ON c.id = r.strategy_configuration_id ORDER BY a.id"
    )


async def test_the_money_plan_account_keeps_its_own_limits(world: World) -> None:
    account = await plan_account(world)
    assert account.starting_balance == D(1000)
    assert account.profile.max_open_positions == 10
    assert account.profile.max_open_risk_fraction == D("0.03")
    assert account.profile.daily_profit_stop_fraction == D("0.03")
    assert world.account.profile.max_open_risk_fraction is None, "other accounts are unchanged"


async def test_signals_at_one_close_get_their_evidence_share_when_they_fit(world: World) -> None:
    """D045: the daily trend risks the full 1%, the pattern half and the baseline a quarter."""
    account = await plan_account(world)
    setups = [await plan_setup(world, who, "98.00") for who in (BASELINE, PATTERN, TREND)]
    outcomes = await world.signals.run_plan(world.provider_id, NOW, account, setups)
    assert all(outcome.approved for outcome in outcomes), [o.reasons for o in outcomes]
    planned = await plan_rows()
    assert [(row["name"], D(row["share"])) for row in planned] == [
        ("daily_trend", D(1)),
        ("pattern_breakout", D("0.5")),
        ("trend_break_baseline", D("0.25")),
    ]
    limits = (D(10), D(5), D("2.5"))
    assert all(row["max_account_risk"] <= cap for row, cap in zip(planned, limits, strict=True))
    assert planned[0]["max_account_risk"] > D("9.9")
    state = await world.paper_repository.account_state(account.id, D(1000), NOW)
    # Stored risk is rounded to 18 places, the per-unit figure times quantity is not.
    stored = sum(row["max_account_risk"] for row in planned)
    assert abs(state.open_risk - stored) < D("1e-12")
    assert await world.records.decided(account.id, NOW)
    assert not await world.records.decided(world.account.id, NOW)


async def test_when_room_runs_short_the_best_evidence_is_served_first(world: World) -> None:
    """A 1% stop makes each trade large, so the account's size limit binds before risk."""
    account = await plan_account(world)
    setups = [await plan_setup(world, who, "99.00") for who in (BASELINE, PATTERN, TREND)]
    await world.signals.run_plan(world.provider_id, NOW, account, setups)
    trend, pattern, baseline = await plan_rows()
    assert trend["decision"] == "APPROVED" and D(trend["share"]) == D(1)
    assert pattern["decision"] == "APPROVED"
    assert D(0) < D(pattern["share"]) < D("0.5") == D(pattern["evidence"])
    assert trend["notional"] + pattern["notional"] <= D(1000)
    assert baseline["decision"] == "REJECTED"
    assert "EXPOSURE_EXCEEDED" in baseline["rejection_codes"]
    assert D(baseline["share"]) == D("0.25"), "a signal with no room is refused at its own share"


async def test_the_money_plan_holds_one_position_per_strategy_and_coin(world: World) -> None:
    account = await plan_account(world)
    trend = await plan_setup(world, TREND, "98.00")
    assert (await world.signals.run_plan(world.provider_id, NOW, account, [trend]))[0].approved
    [again] = await world.signals.run_plan(world.provider_id, NOW, account, [trend])
    assert again.reasons == ("a position from this strategy is open",)
    assert again.recommendation_id is None
