"""The dashboard's view of the owner's real futures wallet (D060), and closes asked from it.

The API reads what the quant worker saved and stores closes for it to carry out. It holds no
key and sends nothing to Binance.
"""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.conftest import make_settings
from tests.integration.test_api_exchange_demo import account_id as demo_account_id
from tests.integration.test_api_exchange_demo import save as save_demo
from tests.integration.test_api_forecasts import EMAIL, ORIGIN, PASSWORD, logged_in
from trading_intel.database.engine import create_engine
from trading_intel.database.repositories.exchange import ExchangeRepository
from trading_intel.database.repositories.signals import SignalRepository
from trading_intel.execution.trader import Budget, ExchangeView, OrderRecord, Position, describe
from trading_intel.trade_signals.exchange_accounts import LIVE

pytestmark = pytest.mark.integration

LIVE_API = "/api/v1/exchange-live"
FROM_DASHBOARD = {"Origin": ORIGIN}


@pytest.fixture
def api(clean_database: None, tmp_path: Path) -> Iterator[TestClient]:
    yield from logged_in(tmp_path, kronos=False)


async def connect(
    armed: bool = False,
    problems: tuple[str, ...] = ("the key can withdraw: turn it off",),
    checked: bool = False,
    age: timedelta = timedelta(0),
) -> UUID:
    """What the quant worker leaves after its first minute checks: the account, made from the
    150 USDT it saw, a bot trade on SOL, and the owner's own ETH short."""
    engine = create_engine(make_settings().database_url)
    account = await SignalRepository(engine).ensure_account(
        EMAIL, LIVE.name, D(150), LIVE.profile, mode=LIVE.mode
    )
    assert account is not None
    orders = ExchangeRepository(engine)
    await orders.day_start(account.id, datetime.now(UTC).date(), D(150))
    entry = OrderRecord("SOLUSDT", "entry", "ati-s-entry", {"type": "MARKET"}, {"orderId": 5})
    await orders.record(account.id, None, entry, trade_key="sol-key", stop_price=D("86.10"))
    if armed:
        await orders.set_armed(account.id, True, EMAIL, "test")
    sol = Position("SOLUSDT", D("-0.5"), D("84.10"), D("41.9"), D("41.9"), D("83.80"), D("0.15"))
    eth = Position("ETHUSDT", D("-0.1"), D("3000"), D("300"), D("100"), D("2990"), D("1"))
    view = ExchangeView(D("151.15"), D("9.25"), {"SOLUSDT": sol, "ETHUSDT": eth})
    stop = {
        "symbol": "SOLUSDT",
        "orderType": "STOP_MARKET",
        "side": "BUY",
        "triggerPrice": "86.10",
        "closePosition": True,
        "clientAlgoId": "ati-s-stop",
    }
    mine = {"symbol": "ETHUSDT", "orderType": "STOP_MARKET", "side": "BUY",
            "triggerPrice": "3300", "closePosition": True, "clientAlgoId": "web_abc"}  # fmt: skip
    body = describe(view, [stop, mine], Budget.wallet(view, D(150), D(0)), D(150), {"SOLUSDT"})
    body["live"] = {
        "armed": armed, "armed_at": None, "armed_by": None,
        "checked_at": datetime.now(UTC).isoformat() if checked else None,
        "problems": list(problems), "ip_restricted": False,
    }  # fmt: skip
    await orders.save_status(account.id, datetime.now(UTC) - age, body)
    await engine.dispose()
    return account.id


async def audit(action: str) -> list[Any]:
    engine = create_engine(make_settings().database_url)
    async with engine.connect() as connection:
        result = await connection.execute(
            text("SELECT actor, object_id, after FROM audit_log WHERE action = :action"),
            {"action": action},
        )
        found = [dict(row._mapping) for row in result]
    await engine.dispose()
    return found


def test_before_the_worker_sees_usdt_the_real_account_is_not_connected(api: TestClient) -> None:
    body = api.get(f"{LIVE_API}/status").json()
    assert body["connected"] is False and body["test_funds"] is False
    assert body["capital"] == "0" and body["live"] is None
    assert api.get(f"{LIVE_API}/limits").status_code == 404
    assert api.get(f"{LIVE_API}/results").status_code == 404
    response = api.get("/api/v1/signals?account=binance_live")
    assert response.status_code == 200 and response.json() == []
    assert asyncio.run(_accounts()) == 0, "reading never makes the real account"


async def _accounts() -> int:
    engine = create_engine(make_settings().database_url)
    async with engine.connect() as connection:
        count = (
            await connection.execute(
                text("SELECT count(*) FROM trading_accounts WHERE mode = 'exchange_live'")
            )
        ).scalar_one()
    await engine.dispose()
    return int(count)


def test_the_real_account_shows_what_was_put_in_and_marks_the_owners_own(api: TestClient) -> None:
    api.get(f"{LIVE_API}/status")  # The owner exists once the app has started.
    asyncio.run(connect())
    body = api.get(f"{LIVE_API}/status").json()
    assert body["connected"] is True and body["test_funds"] is False
    assert body["capital"] == "150" and body["equity"] == "151.15"
    assert body["loss_floor"] == "120", "20% below what was put in"
    owners = {p["symbol"]: p["bot"] for p in body["positions"]}
    assert owners == {"ETHUSDT": False, "SOLUSDT": True}
    assert {o["symbol"]: o["bot"] for o in body["orders"]} == {"ETHUSDT": False, "SOLUSDT": True}
    live = body["live"]
    assert live["armed"] is False and live["problems"] == ["the key can withdraw: turn it off"]
    limits = api.get(f"{LIVE_API}/limits").json()
    assert limits["risk_per_trade"] == "0.01" and limits["loss_stop"] == "0.2"
    results = api.get(f"{LIVE_API}/results").json()
    assert results["test_funds"] is False and results["start_equity"] == "150"


def test_a_close_is_asked_only_from_the_dashboard_and_only_for_the_bots_trade(
    api: TestClient,
) -> None:
    api.get(f"{LIVE_API}/status")
    asyncio.run(connect())
    close = f"{LIVE_API}/positions/SOLUSDT/close"
    assert api.post(close).status_code == 403
    assert api.post(close, headers={"Origin": "https://example.invalid"}).status_code == 403
    mine = api.post(f"{LIVE_API}/positions/ETHUSDT/close", headers=FROM_DASHBOARD)
    assert mine.status_code == 404, "the owner's own position is theirs to close"
    assert api.post(f"{LIVE_API}/positions/sol;drop/close", headers=FROM_DASHBOARD).status_code in (
        404,
        422,
    )
    first = api.post(close, headers=FROM_DASHBOARD)
    assert first.status_code == 202, first.text
    asked = first.json()
    assert asked["symbol"] == "SOLUSDT" and asked["outcome"] is None and asked["done_at"] is None
    again = api.post(close, headers=FROM_DASHBOARD).json()
    assert again["id"] == asked["id"], "one waiting close per coin"
    assert api.get(f"{LIVE_API}/status").json()["closing"] == ["SOLUSDT"]
    [listed] = api.get(f"{LIVE_API}/closes").json()
    assert listed["id"] == asked["id"]
    logged = asyncio.run(audit("exchange_live_close_requested"))
    assert len(logged) == 2 and logged[0]["actor"] == EMAIL
    assert logged[0]["after"] == {"account": LIVE.name, "symbol": "SOLUSDT"}


def test_the_real_accounts_limits_change_as_their_own_logged_version(api: TestClient) -> None:
    api.get(f"{LIVE_API}/status")
    asyncio.run(connect())
    changed = {
        "risk_per_trade": "0.02", "open_risk": "0.04", "exposure": "1", "max_leverage": "3",
        "daily_loss": "0.03", "daily_profit_stop": "0.03", "loss_stop": "0.2",
        "loss_stop_from_high": False,
    }  # fmt: skip
    assert api.put(f"{LIVE_API}/limits", json=changed).status_code == 403
    response = api.put(f"{LIVE_API}/limits", json=changed, headers=FROM_DASHBOARD)
    assert response.status_code == 200, response.text
    assert response.json()["risk_per_trade"] == "0.02"
    assert len(asyncio.run(audit("exchange_live_limits_changed"))) == 1
    demo = api.get("/api/v1/exchange-demo/limits").json()
    assert demo["risk_per_trade"] != "0.02", "the demo account keeps its own limits"


def test_a_demo_trade_can_be_closed_from_the_dashboard_too(api: TestClient) -> None:
    api.get("/api/v1/exchange-demo/status")
    asyncio.run(save_demo(asyncio.run(demo_account_id())))
    response = api.post("/api/v1/exchange-demo/positions/SOLUSDT/close", headers=FROM_DASHBOARD)
    assert response.status_code == 202, response.text
    assert len(asyncio.run(audit("exchange_demo_close_requested"))) == 1


ARMING = f"{LIVE_API}/arming"


def test_real_trading_turns_on_only_with_the_password_and_a_clean_check(api: TestClient) -> None:
    """D063: the switch on the dashboard. Off needs nothing; on needs the password, a running
    bot and no problem in its check of the key and the account. Every attempt is logged."""
    api.get(f"{LIVE_API}/status")
    asyncio.run(connect())  # The check found a key that can withdraw.
    on = {"armed": True, "password": PASSWORD}
    assert api.put(ARMING, json=on).status_code == 403, "from the dashboard only"
    wrong = api.put(ARMING, json={**on, "password": "not-it"}, headers=FROM_DASHBOARD)
    assert wrong.status_code == 403 and "password" in wrong.json()["error"]["message"]
    blocked = api.put(ARMING, json=on, headers=FROM_DASHBOARD)
    assert blocked.status_code == 409 and "withdraw" in blocked.json()["error"]["message"]
    assert api.get(f"{LIVE_API}/status").json()["live"]["armed"] is False
    asyncio.run(connect(problems=(), checked=True))  # The owner fixed the key on Binance.
    armed = api.put(ARMING, json=on, headers=FROM_DASHBOARD)
    assert armed.status_code == 200, armed.text
    assert armed.json()["armed"] is True and armed.json()["armed_at"] is not None
    assert api.get(f"{LIVE_API}/status").json()["live"]["armed"] is True, "shown at once"
    off = api.put(ARMING, json={"armed": False}, headers=FROM_DASHBOARD)
    assert off.status_code == 200 and off.json()["armed"] is False, "off needs no password"
    actions = [row["actor"] for row in asyncio.run(audit("exchange_live_arm_refused"))]
    assert actions == [EMAIL]
    assert len(asyncio.run(audit("exchange_live_armed"))) == 1
    assert len(asyncio.run(audit("exchange_live_disarmed"))) == 1


def test_real_trading_stays_off_while_the_bot_is_not_running(api: TestClient) -> None:
    api.get(f"{LIVE_API}/status")
    asyncio.run(connect(problems=(), checked=True, age=timedelta(minutes=10)))
    stale = api.put(ARMING, json={"armed": True, "password": PASSWORD}, headers=FROM_DASHBOARD)
    assert stale.status_code == 409 and "not running" in stale.json()["error"]["message"]


def test_demo_trading_switches_off_and_on_without_a_password(api: TestClient) -> None:
    """D064: demo trading's test funds trade until switched off, and need no password."""
    before = api.put(ARMING, json={"armed": False}, headers=FROM_DASHBOARD)
    assert before.status_code == 404, "no real account yet"
    demo = "/api/v1/exchange-demo"
    assert api.get(f"{demo}/status").json()["armed"] is True, "on until switched off"
    assert api.put(f"{demo}/arming", json={"armed": False}).status_code == 403
    off = api.put(f"{demo}/arming", json={"armed": False}, headers=FROM_DASHBOARD)
    assert off.status_code == 200 and off.json()["armed"] is False
    assert api.get(f"{demo}/status").json()["armed"] is False
    on = api.put(f"{demo}/arming", json={"armed": True}, headers=FROM_DASHBOARD)
    assert on.status_code == 200 and on.json()["armed"] is True
    assert len(asyncio.run(audit("exchange_demo_disarmed"))) == 1
    assert len(asyncio.run(audit("exchange_demo_armed"))) == 1
