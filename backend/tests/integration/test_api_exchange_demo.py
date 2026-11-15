"""The dashboard's Binance demo view (D048), read from what the quant worker saved."""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal as D
from pathlib import Path
from typing import Any
from uuid import UUID, uuid7

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.conftest import make_settings
from tests.integration.test_api_forecasts import EMAIL, ORIGIN, logged_in
from trading_intel.database.engine import create_engine
from trading_intel.database.repositories.exchange import ExchangeRepository
from trading_intel.database.repositories.signals import (
    EXCHANGE_DEMO_ACCOUNT,
    EXCHANGE_DEMO_BUDGET,
    EXCHANGE_DEMO_MODE,
    Account,
    SignalRepository,
)
from trading_intel.execution.trader import Budget, ExchangeView, OrderRecord, Position, describe
from trading_intel.trade_signals.portfolio import EXCHANGE_DEMO_PROFILE

pytestmark = pytest.mark.integration

STATUS = "/api/v1/exchange-demo/status"


@pytest.fixture
def api(clean_database: None, tmp_path: Path) -> Iterator[TestClient]:
    yield from logged_in(tmp_path, kronos=False)


async def demo_account() -> Account:
    engine = create_engine(make_settings().database_url)
    account = await SignalRepository(engine).ensure_account(
        EMAIL, EXCHANGE_DEMO_ACCOUNT, EXCHANGE_DEMO_BUDGET, EXCHANGE_DEMO_PROFILE,
        mode=EXCHANGE_DEMO_MODE,
    )  # fmt: skip
    await engine.dispose()
    assert account is not None
    return account


async def account_id() -> UUID:
    return (await demo_account()).id


async def save(account: UUID, records: list[OrderRecord] | None = None) -> None:
    engine = create_engine(make_settings().database_url)
    repository = ExchangeRepository(engine)
    short = Position(
        "SOLUSDT", D("-0.5"), D("84.10"), D("41.9"), D("41.9"), D("83.80"), D("0.15"), D("160.2")
    )
    view = ExchangeView(D("5000.15"), D("4958.25"), {"SOLUSDT": short})
    stop = {"symbol": "SOLUSDT", "orderType": "STOP_MARKET", "side": "BUY",
            "triggerPrice": "86.10", "closePosition": True}  # fmt: skip
    target = {"symbol": "SOLUSDT", "orderType": "TAKE_PROFIT_MARKET", "side": "BUY",
              "triggerPrice": "80.10", "quantity": "0.25", "closePosition": False}  # fmt: skip
    budget = Budget.of(view, D(100), D(5000), D(5000))
    body = describe(view, [stop, target], budget, D(100))
    await repository.save_status(account, datetime.now(UTC), body)
    for record in records or []:
        await repository.record(account, None, record)
    await engine.dispose()


def test_before_the_worker_saves_anything_the_view_says_so(api: TestClient) -> None:
    response = api.get(STATUS)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["connected"] is False and body["capital"] == "100"
    assert body["test_funds"] is True and body["positions"] == []
    # D053: new trades stop for good at 80 USDT, 20 below the budget.
    assert body["loss_floor"] == "80" and body["loss_stopped_at"] is None


def test_a_reached_loss_stop_is_shown_with_its_time(api: TestClient) -> None:
    api.get(STATUS)
    account = asyncio.run(demo_account())

    async def reach() -> None:
        engine = create_engine(make_settings().database_url)
        await ExchangeRepository(engine).record_loss_stop(
            account.id, account.risk_profile_id, datetime(2026, 11, 12, 3, tzinfo=UTC), D(79),
            D(80),
        )  # fmt: skip
        await engine.dispose()

    asyncio.run(reach())
    body = api.get(STATUS).json()
    assert body["loss_stopped_at"] == "2026-11-12T03:00:00Z" and body["loss_floor"] == "80"


def test_the_view_shows_the_budget_positions_and_the_stops_binance_holds(api: TestClient) -> None:
    api.get(STATUS)  # The owner exists once the app has started.
    asyncio.run(save(asyncio.run(account_id())))
    body = api.get(STATUS).json()
    assert body["connected"] is True and 0 <= body["age_seconds"] < 60
    assert body["binance_equity"] == "5000.15" and body["capital"] == "100"
    assert body["equity"] == "100.15"  # 100 plus the bot's own 0.15 USDT.
    assert body["available"] == "58.25"
    [position] = body["positions"]
    assert position["side"] == "SHORT" and position["quantity"] == "0.5"
    assert position["liquidation"] == "160.2"
    stop, target = body["orders"]
    assert target["type"] == "TAKE_PROFIT_MARKET" and target["quantity"] == "0.25"
    assert stop["type"] == "STOP_MARKET" and stop["close_position"] is True
    assert stop["quantity"] is None


def test_orders_show_what_binance_accepted_refused_or_never_answered(api: TestClient) -> None:
    api.get(STATUS)
    account = asyncio.run(account_id())
    entry = OrderRecord(
        "SOLUSDT", "entry", "ati-a-entry", {"side": "SELL", "type": "MARKET", "quantity": "0.5"},
        {"executedQty": "0.5", "avgPrice": "84.10"},
    )  # fmt: skip
    refused = OrderRecord(
        "SOLUSDT", "stop", "ati-a-stop", {"side": "BUY", "triggerPrice": "86.10"}, None,
        "Binance 400 -2021: Order would immediately trigger.",
    )  # fmt: skip
    lost = OrderRecord(
        "XRPUSDT", "entry", "ati-b-entry", {"side": "BUY"}, None, "no reply: ReadTimeout"
    )
    asyncio.run(save(account, [entry, refused, lost]))
    rows = api.get("/api/v1/exchange-demo/orders").json()
    by_kind = {(row["symbol"], row["kind"]): row for row in rows}
    accepted = by_kind[("SOLUSDT", "entry")]
    assert accepted["outcome"] == "accepted" and accepted["average_price"] == "84.10"
    assert accepted["executed"] == "0.5" and accepted["side"] == "SELL"
    assert by_kind[("SOLUSDT", "stop")]["outcome"] == "refused"
    assert by_kind[("SOLUSDT", "stop")]["trigger"] == "86.10"
    assert by_kind[("XRPUSDT", "entry")]["outcome"] == "no reply"


def test_a_cancel_is_named_as_one(api: TestClient) -> None:
    api.get(STATUS)
    account = asyncio.run(account_id())
    cancel = OrderRecord(
        "SOLUSDT", "stop", "ati-old-stop", {"cancel": "algoOrder", "algoId": 7},
        {"algoId": 7, "code": "200", "msg": "success"},
    )  # fmt: skip
    asyncio.run(save(account, [cancel]))
    [row] = api.get("/api/v1/exchange-demo/orders").json()
    assert row["type"] == "CANCEL" and row["kind"] == "stop" and row["outcome"] == "accepted"


def test_signals_can_be_read_for_the_binance_demo_account(api: TestClient) -> None:
    response = api.get("/api/v1/signals?account=binance")
    assert response.status_code == 200 and response.json() == []
    assert api.get("/api/v1/signals?account=live").status_code == 422


def test_the_signals_pages_filters_are_checked_before_any_query(api: TestClient) -> None:
    """D065: every filter of the Signals page, and the chart link's single signal."""
    every = (
        "account=binance&instrument_id=1&strategy=trend_break_baseline&action=BUY"
        "&decision=APPROVED&result=entered&period=7d&limit=500"
    )
    assert api.get(f"/api/v1/signals?{every}").json() == []
    for bad in (
        "action=HOLD", "decision=MAYBE", "result=lucky", "period=1y", "limit=501",
        "instrument_id=0", "strategy=DROP%20TABLE",
    ):  # fmt: skip
        assert api.get(f"/api/v1/signals?{bad}").status_code == 422, bad
    for account in ("binance", "binance_live"):
        missing = api.get(f"/api/v1/signals/{uuid7()}?account={account}")
        assert missing.status_code == 404, account
        assert missing.json()["error"]["code"] == "not_found"
    assert api.get("/api/v1/signals/not-a-signal").status_code == 422


def test_results_before_any_completed_trade_start_at_the_budget(api: TestClient) -> None:
    """D057: with no completed trade the results are empty, and the curve is the budget."""
    for period in ("7d", "30d", "all"):
        response = api.get("/api/v1/exchange-demo/results", params={"period": period})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["test_funds"] is True and body["period"] == period
        assert body["summary"]["trades"] == 0 and body["summary"]["win_rate"] is None
        assert body["summary"]["profit_factor"] is None and body["trades"] == []
        assert body["start_equity"] == "100" and [p["equity"] for p in body["equity"]] == ["100"]
        assert body["by_coin"] == [] and body["grid"] == [] and body["open_trades"] == 0
    assert api.get("/api/v1/exchange-demo/results", params={"period": "1y"}).status_code == 422


LIMITS = "/api/v1/exchange-demo/limits"
NEW_LIMITS = {
    "risk_per_trade": "0.05",
    "open_risk": "0.08",
    "exposure": "0.8",
    "max_leverage": "2",
    "daily_loss": "0.06",
    "daily_profit_stop": None,
    "loss_stop": "0.25",
    "loss_stop_from_high": True,
}


def test_the_limits_and_their_ceilings_are_shown(api: TestClient) -> None:
    body = api.get(LIMITS).json()
    assert body["risk_per_trade"] == "0.1" and body["open_risk"] == "0.1"
    assert body["exposure"] == "0.8" and body["daily_loss"] == "0.1"
    assert body["loss_stop"] == "0.2" and body["loss_stop_from_high"] is False
    assert body["ceilings"] == {
        "risk_per_trade": "0.1", "open_risk": "0.1", "daily_loss": "0.1",
        "leverage": "5", "exposure": "5",
    }  # fmt: skip


def test_saved_limits_become_a_new_logged_version(api: TestClient) -> None:
    before = api.get(LIMITS).json()
    response = api.put(LIMITS, json=NEW_LIMITS, headers={"Origin": ORIGIN})
    assert response.status_code == 200, response.text
    after = response.json()
    assert after["version"] == before["version"] + 1
    assert after["risk_per_trade"] == "0.05" and after["max_leverage"] == "2"
    assert after["daily_profit_stop"] is None and after["loss_stop_from_high"] is True
    [audit] = asyncio.run(audit_rows())
    assert audit["action"] == "exchange_demo_limits_changed"
    assert audit["after"]["risk_per_trade"] == "0.05"


def test_limits_change_only_from_the_dashboard_and_within_the_ceilings(api: TestClient) -> None:
    api.get(LIMITS)
    assert api.put(LIMITS, json=NEW_LIMITS).status_code == 403
    elsewhere = {"Origin": "https://example.invalid"}
    assert api.put(LIMITS, json=NEW_LIMITS, headers=elsewhere).status_code == 403
    for bad in ({"risk_per_trade": "0.11"}, {"open_risk": "0.04"}, {"max_leverage": "6"}):
        response = api.put(LIMITS, json={**NEW_LIMITS, **bad}, headers={"Origin": ORIGIN})
        assert response.status_code == 400, bad
        assert "not allowed" in response.json()["error"]["message"]
    assert api.get(LIMITS).json()["risk_per_trade"] == "0.1", "nothing was saved"


async def audit_rows() -> list[Any]:
    engine = create_engine(make_settings().database_url)
    async with engine.connect() as connection:
        result = await connection.execute(
            text("SELECT action, after FROM audit_log WHERE object_type = 'risk_profile'")
        )
        found = [dict(row._mapping) for row in result]
    await engine.dispose()
    return found


def test_one_trade_can_be_limited_to_a_share_of_equity(api: TestClient) -> None:
    """D061: room for 300% of equity, and no single position above 100%."""
    room = {**NEW_LIMITS, "exposure": "3", "largest_trade": "1", "max_leverage": "5"}
    response = api.put(LIMITS, json=room, headers={"Origin": ORIGIN})
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["exposure"] == "3" and saved["largest_trade"] == "1"
    assert api.get(LIMITS).json()["largest_trade"] == "1"
    past = api.put(LIMITS, json={**room, "largest_trade": "4"}, headers={"Origin": ORIGIN})
    assert past.status_code == 400, "one trade can never pass all positions together"
    cleared = api.put(LIMITS, json={**room, "largest_trade": None}, headers={"Origin": ORIGIN})
    assert cleared.json()["largest_trade"] is None


def test_one_direction_can_be_limited_to_a_share_of_equity(api: TestClient) -> None:
    """D072: longs together, or shorts together, at most this share of equity."""
    response = api.put(
        LIMITS, json={**NEW_LIMITS, "one_direction": "0.6"}, headers={"Origin": ORIGIN}
    )
    assert response.status_code == 200, response.text
    assert response.json()["one_direction"] == "0.6"
    assert api.get(LIMITS).json()["one_direction"] == "0.6"
    past = api.put(LIMITS, json={**NEW_LIMITS, "one_direction": "4"}, headers={"Origin": ORIGIN})
    assert past.status_code == 400, "one direction can never pass all positions together"
    cleared = api.put(
        LIMITS, json={**NEW_LIMITS, "one_direction": None}, headers={"Origin": ORIGIN}
    )
    assert cleared.json()["one_direction"] is None
