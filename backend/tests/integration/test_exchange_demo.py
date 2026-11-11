"""The money plan on Binance demo trading (D048), on real PostgreSQL with a fake exchange."""

from datetime import timedelta
from decimal import Decimal as D
from typing import Any

import pytest

from tests.exchange_fakes import FakeGateway
from tests.integration import test_trading_flow as flow
from tests.integration.test_trading_flow import (
    BASELINE,
    EMAIL,
    NOW,
    PATTERN,
    TREND,
    World,
    day,
    plan_setup,
    proposal,
    rows,
)
from trading_intel.database.repositories.exchange import ExchangeRepository
from trading_intel.database.repositories.signals import (
    EXCHANGE_DEMO_ACCOUNT,
    EXCHANGE_DEMO_BUDGET,
    EXCHANGE_DEMO_MODE,
    Account,
)
from trading_intel.domain.candles import Timeframe
from trading_intel.domain.signals import Action, EntryType
from trading_intel.execution.trader import FuturesTrader
from trading_intel.risk_management.models import RiskProfile
from trading_intel.trade_signals.baseline import BaselineDecision
from trading_intel.trade_signals.portfolio import EXCHANGE_DEMO_PROFILE, PLAN_PROFILE
from trading_intel.trade_signals.service import Setup, StrategyIdentity

pytestmark = pytest.mark.integration

world = flow.world  # The trading flow's fixture: one coin, a live book and an owner.


async def demo_account(world: World, limits: RiskProfile = PLAN_PROFILE) -> Account:
    """The paper plan's limits test the mechanics; the owner's limits (D053) have own tests."""
    account = await world.records.ensure_account(
        EMAIL, EXCHANGE_DEMO_ACCOUNT, EXCHANGE_DEMO_BUDGET, limits, mode=EXCHANGE_DEMO_MODE
    )
    assert account is not None
    return account


async def run(
    world: World,
    exchange: FakeGateway,
    stop: str = "98.00",
    *,
    signals: bool = True,
    limits: RiskProfile = PLAN_PROFILE,
) -> tuple[Account, Any]:
    account = await demo_account(world, limits)
    who = (BASELINE, PATTERN, TREND) if signals else ()
    setups = [await plan_setup(world, strategy, stop) for strategy in who]
    repository = ExchangeRepository(world.signals._rules._engine)
    outcomes = await world.signals.run_exchange_plan(
        world.provider_id, NOW, account, setups, FuturesTrader(exchange), repository
    )
    return account, outcomes


async def assessments() -> list[Any]:
    return await rows(
        "SELECT c.name, a.decision, a.rejection_codes, a.max_account_risk, "
        "a.inputs->>'leverage' AS leverage, a.inputs->>'risk_share' AS share "
        "FROM risk_assessments a JOIN trade_recommendations r ON r.id = a.recommendation_id "
        "JOIN strategy_configurations c ON c.id = r.strategy_configuration_id ORDER BY a.id"
    )


async def test_the_strongest_signal_trades_on_binance_with_its_stop_and_targets(
    world: World,
) -> None:
    exchange = FakeGateway(filled=None)
    account, outcomes = await run(world, exchange)
    symbol = world.instrument.symbol
    traded, *refused = outcomes
    assert traded.approved
    assert [o.reasons for o in refused] == [("a position on this coin is open on Binance",)] * 2
    [row] = await assessments()
    assert row["name"] == "daily_trend" and D(row["share"]) == D(1) and row["leverage"] == "1"
    # 1% of the 100 USDT budget, not of the 5,000 test USDT Binance holds.
    assert D("0.98") < row["max_account_risk"] <= D(1)
    kinds = [call[0] for call in exchange.calls]
    assert kinds == ["isolated", "leverage", "market", "STOP_MARKET"] + ["TAKE_PROFIT_MARKET"] * 3
    assert exchange.calls[3] == ("STOP_MARKET", symbol, "SELL", D("98.00"), None)
    stored = await rows(
        "SELECT kind, stop_price, recommendation_id FROM exchange_orders ORDER BY created_at, kind"
    )
    assert sorted(r["kind"] for r in stored) == ["entry", "stop", "tp1", "tp2", "tp3"]
    assert all(r["recommendation_id"] == traded.recommendation_id for r in stored)
    stops = await ExchangeRepository(world.signals._rules._engine).stops(account.id)
    assert stops[symbol][0] == D("98.00")
    paper = await rows(
        f"SELECT count(*) AS n FROM paper_positions WHERE account_id = '{account.id}'"
    )
    assert paper[0]["n"] == 0, "an exchange account opens no paper position"


async def test_leverage_rises_only_until_the_margin_fits(world: World) -> None:
    exchange = FakeGateway(filled=None, available="30")
    await run(world, exchange)
    [row] = await assessments()
    assert row["decision"] == "APPROVED" and row["leverage"] == "2"
    assert ("leverage", world.instrument.symbol, 2) in exchange.calls
    assert D("0.98") < row["max_account_risk"] <= D(1), "leverage never changes the risk"


async def test_a_signal_needing_more_than_3x_is_refused_and_a_smaller_one_can_fit(
    world: World,
) -> None:
    """The trend's full share does not fit at 3x. The pattern's half share does, so it trades."""
    exchange = FakeGateway(filled=None, available="10")
    _, outcomes = await run(world, exchange)
    trend, pattern = await assessments()
    assert trend["name"] == "daily_trend" and trend["decision"] == "REJECTED"
    assert trend["leverage"] == "3" and "MARGIN_INSUFFICIENT" in trend["rejection_codes"]
    assert pattern["name"] == "pattern_breakout" and pattern["decision"] == "APPROVED"
    assert pattern["leverage"] == "3" and D(pattern["share"]) == D("0.5")
    assert [o.approved for o in outcomes] == [False, True, False]
    assert outcomes[2].reasons == ("a position on this coin is open on Binance",)
    assert sum(1 for call in exchange.calls if call[0] == "market") == 1


async def test_a_coin_with_a_binance_position_takes_no_new_signal(world: World) -> None:
    held = {
        "symbol": world.instrument.symbol,
        "positionAmt": "-3",
        "entryPrice": "101",
        "notional": "300",
    }
    exchange = FakeGateway(positions=[held])
    _, outcomes = await run(world, exchange)
    assert all(o.reasons == ("a position on this coin is open on Binance",) for o in outcomes)
    assert await assessments() == [] and exchange.calls == []


async def test_the_day_start_equity_is_the_first_seen_that_day(world: World) -> None:
    account = await demo_account(world)
    repository = ExchangeRepository(world.signals._rules._engine)
    assert await repository.day_start(account.id, NOW.date(), D(5000)) == D(5000)
    assert await repository.day_start(account.id, NOW.date(), D(4000)) == D(5000)


async def test_only_paper_and_exchange_demo_accounts_can_exist(world: World) -> None:
    account = await demo_account(world)
    [stored] = await rows(f"SELECT mode FROM trading_accounts WHERE id = '{account.id}'")
    assert stored["mode"] == "exchange_demo"


async def test_the_budget_follows_the_bots_profit_and_loss_on_binance(world: World) -> None:
    """Binance's equity is 5,000 at the first close, so that is where the 100 USDT begins.

    A 10 USDT loss there leaves a 90 USDT budget, 10% down on the day, so the 3% daily loss
    limit refuses every new trade.
    """
    await run(world, FakeGateway(equity="5000"), signals=False)
    _, outcomes = await run(world, FakeGateway(equity="4990"))
    assert not any(outcome.approved for outcome in outcomes)
    refused = await assessments()
    assert len(refused) == 3
    assert all("DAILY_LOSS_REACHED" in row["rejection_codes"] for row in refused)


async def test_a_daily_trend_position_on_binance_trails_its_stop(world: World) -> None:
    """Regression: only paper stops trailed, so the SOL trend short on Binance kept its first
    stop and had no other exit (2026-11-11). Same candles as the paper trailing test."""
    account, _ = await run(world, FakeGateway(filled=None))
    symbol = world.instrument.symbol
    await world.candles.insert(
        [day(world, n, str(100 + (30 - n)), str(102 + (30 - n))) for n in range(30, 0, -1)]
    )
    last_close = Timeframe.D1.close_time(Timeframe.D1.floor(NOW) - timedelta(days=1))
    held = {"symbol": symbol, "positionAmt": "0.5", "entryPrice": "100", "notional": "50"}
    stop = {"symbol": symbol, "orderType": "STOP_MARKET", "algoId": 4, "triggerPrice": "98.00"}
    exchange = FakeGateway(positions=[held], algo=[stop])
    repository = ExchangeRepository(world.signals._rules._engine)

    async def trail() -> bool:
        return await world.signals.trail_exchange_stop(
            world.provider_id, world.instrument, last_close, account,
            FuturesTrader(exchange), repository,
        )  # fmt: skip

    assert await trail()
    # The lowest low of the last 10 days, as on paper: the candle 10 days back opened at 120.
    assert exchange.calls == [("cancel one", 4), ("STOP_MARKET", symbol, "SELL", D("120.00"), None)]
    assert (await repository.stops(account.id))[symbol][0] == D("120.00")
    assert not await trail(), "the stop is already at the 10-day low"
    stored = await rows("SELECT kind, request->>'cancel' AS cancel FROM exchange_orders")
    assert sum(1 for r in stored if r["cancel"] == "algoOrder") == 1


async def test_only_the_daily_trend_trails_on_binance(world: World) -> None:
    account = await demo_account(world)
    repository = ExchangeRepository(world.signals._rules._engine)
    exchange = FakeGateway(positions=[{"symbol": world.instrument.symbol, "positionAmt": "1"}])
    assert not await world.signals.trail_exchange_stop(
        world.provider_id, world.instrument, NOW, account, FuturesTrader(exchange), repository
    ), "no trade from this bot is open on the coin"
    assert exchange.calls == []


async def test_each_15m_close_asks_both_15m_strategies(world: World) -> None:
    """docs/35: the 4H gap and 15M CHoCH strategy joined the money plan beside the 15M rule."""
    close = NOW.replace(minute=44, second=59, microsecond=999000)  # A 15M close only.
    setups, missing = await world.signals.plan_setups(world.provider_id, [world.instrument], close)
    # The test world stores no 15M or 4H candles, so both strategies report the coin missing.
    assert setups == []
    assert missing == [f"{world.instrument.symbol} 15m"] * 2


async def test_the_owners_binance_limits_risk_two_percent_of_the_budget(world: World) -> None:
    """D053: the daily trend's full share is 2% of the 100 USDT budget."""
    _, outcomes = await run(world, FakeGateway(filled=None), limits=EXCHANGE_DEMO_PROFILE)
    assert outcomes[0].approved
    [row] = await assessments()
    assert row["name"] == "daily_trend"
    assert D("1.96") < row["max_account_risk"] <= D(2)


async def test_the_loss_stop_holds_until_the_owner_sets_new_limits(world: World) -> None:
    """D053: 20 USDT lost from the 100 USDT budget stops the bot, and a recovery does not
    restart it. Only a new profile version, the owner's next decision, does."""
    owner = EXCHANGE_DEMO_PROFILE
    await run(world, FakeGateway(equity="5000"), signals=False, limits=owner)
    account, outcomes = await run(world, FakeGateway(equity="4980"), limits=owner)
    [stopped] = outcomes
    assert stopped.reasons[0].startswith("stopped by its loss stop at")
    assert not stopped.approved and await assessments() == []
    [kept] = await rows("SELECT equity, floor, risk_profile_id FROM exchange_loss_stops")
    assert kept["equity"] == D(80) and kept["floor"] == D(80)
    assert kept["risk_profile_id"] == account.risk_profile_id

    _, outcomes = await run(world, FakeGateway(equity="4999", filled=None), limits=owner)
    assert [o.reasons[0][:27] for o in outcomes] == ["stopped by its loss stop at"]
    assert await assessments() == [], "back at 99 USDT, it still waits for the owner"

    await rows(
        f"""INSERT INTO risk_profiles (account_id, version, max_risk_fraction, min_reward_risk,
              countertrend_extra_rr, max_daily_loss_fraction, max_open_positions,
              max_total_exposure_fraction, max_leverage, max_spread_bps, max_data_age_seconds,
              settings)
            SELECT account_id, version + 1, max_risk_fraction, min_reward_risk,
              countertrend_extra_rr, max_daily_loss_fraction, max_open_positions,
              max_total_exposure_fraction, max_leverage, max_spread_bps, max_data_age_seconds,
              settings
            FROM risk_profiles WHERE account_id = '{account.id}' ORDER BY version DESC LIMIT 1"""
    )
    _, outcomes = await run(world, FakeGateway(equity="4999", filled=None), limits=owner)
    assert outcomes[0].approved, "new limits from the owner let it trade again"


async def test_a_trade_is_shrunk_so_its_stop_cannot_pass_the_loss_stop(world: World) -> None:
    """The budget began at 5,000 on Binance yesterday and starts today 19 USDT down, at 81. Only
    1 USDT is left above the 80 USDT stop, so the trend risks at most 1, not 2% (1.62)."""
    account = await demo_account(world, EXCHANGE_DEMO_PROFILE)
    await rows(
        f"""INSERT INTO exchange_equity_days (account_id, day, equity) VALUES
            ('{account.id}', '{NOW.date() - timedelta(days=1)}', 5000),
            ('{account.id}', '{NOW.date()}', 4981)"""
    )
    _, outcomes = await run(
        world, FakeGateway(equity="4981", filled=None), limits=EXCHANGE_DEMO_PROFILE
    )
    assert outcomes[0].approved
    [row] = await assessments()
    assert row["name"] == "daily_trend"
    assert D("0.9") < row["max_account_risk"] <= D(1)


GAP = StrategyIdentity("fvg_choch", 1, {"test": True})


async def limit_setup(world: World) -> Setup:
    """The 4H gap and 15M CHoCH strategy's kind of signal: a limit buy below the book."""
    setup = await plan_setup(world, GAP, "98.00")
    limit = proposal(entry_type=EntryType.LIMIT, entry=D("99.00"), stop=D("98.00"))
    decision = BaselineDecision(Action.BUY, NOW, ("test gap",), proposal=limit, setup_atr=D(1))
    return Setup(world.instrument, setup.rules, decision, GAP, Timeframe.M15)


async def test_a_limit_signal_waits_on_binance_with_its_stop_until_it_expires(
    world: World,
) -> None:
    """D054: the gap strategy's limit entry is sent as GTD to its signal's expiry, with a
    reduce-only stop for the full size and its targets, all before it fills."""
    account = await demo_account(world, EXCHANGE_DEMO_PROFILE)
    exchange = FakeGateway()
    repository = ExchangeRepository(world.signals._rules._engine)
    [outcome] = await world.signals.run_exchange_plan(
        world.provider_id, NOW, account, [await limit_setup(world)], FuturesTrader(exchange),
        repository,
    )  # fmt: skip
    assert outcome.approved
    symbol = world.instrument.symbol
    [limit] = [call for call in exchange.calls if call[0] == "limit"]
    [expiry] = await rows("SELECT expires_at FROM trade_recommendations")
    assert limit[:3] == ("limit", symbol, "BUY") and limit[4] == D("99.00")
    assert limit[5] == int(expiry["expires_at"].timestamp() * 1000)
    assert ("STOP_MARKET", symbol, "SELL", D("98.00"), limit[3]) in exchange.calls
    assert sum(1 for call in exchange.calls if call[0] == "TAKE_PROFIT_MARKET") == 3
    assert not any(call[0] == "market" for call in exchange.calls)
    stored = await repository.stops(account.id)
    assert stored[symbol][0] == D("98.00"), "the stop is recorded for the minute check"


async def test_a_waiting_entry_takes_its_coin_and_counts_its_risk(world: World) -> None:
    waiting = {
        "symbol": world.instrument.symbol, "type": "LIMIT", "side": "BUY", "price": "99",
        "origQty": "1", "executedQty": "0", "reduceOnly": False, "clientOrderId": "ati-w-entry",
    }  # fmt: skip
    exchange = FakeGateway(entries=[waiting])
    _, outcomes = await run(world, exchange, limits=EXCHANGE_DEMO_PROFILE)
    reasons = {o.reasons for o in outcomes}
    assert reasons == {("a limit entry on this coin is waiting on Binance",)}
    assert await assessments() == [] and exchange.calls == []


@pytest.mark.parametrize(
    ("strategy", "risk", "entry"),
    [
        ("daily_trend", D(2), "market"),
        ("pattern_breakout", D(1), "market"),
        ("fvg_choch", D(1), "limit"),
        ("trend_break_baseline", D("0.5"), "market"),
    ],
)
async def test_every_strategy_trades_on_binance_at_its_share_of_two_percent(
    world: World, strategy: str, risk: D, entry: str
) -> None:
    """The owner's request on 2026-11-11: all four strategies trade on Binance demo, each at
    its evidence share of the 2% (D053, D054)."""
    account = await demo_account(world, EXCHANGE_DEMO_PROFILE)
    identity = {"daily_trend": TREND, "pattern_breakout": PATTERN, "fvg_choch": GAP}.get(
        strategy, BASELINE
    )
    setup = await (
        limit_setup(world) if strategy == "fvg_choch" else plan_setup(world, identity, "98.00")
    )
    exchange = FakeGateway(filled=None)
    repository = ExchangeRepository(world.signals._rules._engine)
    [outcome] = await world.signals.run_exchange_plan(
        world.provider_id, NOW, account, [setup], FuturesTrader(exchange), repository
    )
    assert outcome.approved, outcome.reasons
    [row] = await assessments()
    assert row["name"] == strategy
    assert risk * D("0.97") < row["max_account_risk"] <= risk
    assert any(call[0] == entry for call in exchange.calls)
    assert any(call[0] == "STOP_MARKET" for call in exchange.calls)
