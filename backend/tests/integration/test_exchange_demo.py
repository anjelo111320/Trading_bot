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
from trading_intel.execution.trader import FuturesTrader
from trading_intel.trade_signals.portfolio import PLAN_PROFILE

pytestmark = pytest.mark.integration

world = flow.world  # The trading flow's fixture: one coin, a live book and an owner.


async def demo_account(world: World) -> Account:
    account = await world.records.ensure_account(
        EMAIL, EXCHANGE_DEMO_ACCOUNT, EXCHANGE_DEMO_BUDGET, PLAN_PROFILE, mode=EXCHANGE_DEMO_MODE
    )
    assert account is not None
    return account


async def run(
    world: World, exchange: FakeGateway, stop: str = "98.00", *, signals: bool = True
) -> tuple[Account, Any]:
    account = await demo_account(world)
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
