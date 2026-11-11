"""The dashboard's Binance demo view (D048), read from what the quant worker saved."""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal as D
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from tests.conftest import make_settings
from tests.integration.test_api_forecasts import EMAIL, logged_in
from trading_intel.database.engine import create_engine
from trading_intel.database.repositories.exchange import ExchangeRepository
from trading_intel.database.repositories.signals import (
    EXCHANGE_DEMO_ACCOUNT,
    EXCHANGE_DEMO_BUDGET,
    EXCHANGE_DEMO_MODE,
    SignalRepository,
)
from trading_intel.execution.trader import Budget, ExchangeView, OrderRecord, Position, describe
from trading_intel.trade_signals.portfolio import PLAN_PROFILE

pytestmark = pytest.mark.integration

STATUS = "/api/v1/exchange-demo/status"


@pytest.fixture
def api(clean_database: None, tmp_path: Path) -> Iterator[TestClient]:
    yield from logged_in(tmp_path, kronos=False)


async def account_id() -> UUID:
    engine = create_engine(make_settings().database_url)
    account = await SignalRepository(engine).ensure_account(
        EMAIL, EXCHANGE_DEMO_ACCOUNT, EXCHANGE_DEMO_BUDGET, PLAN_PROFILE, mode=EXCHANGE_DEMO_MODE
    )
    await engine.dispose()
    assert account is not None
    return account.id


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
