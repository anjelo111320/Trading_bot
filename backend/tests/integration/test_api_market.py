"""The API against real PostgreSQL and Redis, through real HTTP and WebSocket handling."""

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import asyncpg
import httpx
import pytest
import uvicorn
import websockets
from fastapi.testclient import TestClient
from redis.asyncio import Redis
from starlette.websockets import WebSocketDisconnect
from websockets.exceptions import InvalidStatus

from tests.conftest import make_settings
from tests.fakes import make_candle
from tests.integration.support import SUPERUSER_URL
from trading_intel.api.app import create_app
from trading_intel.core.clock import SystemClock
from trading_intel.database.engine import create_engine
from trading_intel.database.repositories.candles import CandleRepository
from trading_intel.database.repositories.operations import GapRepository
from trading_intel.database.repositories.reference import ReferenceRepository
from trading_intel.domain.base import DataOrigin
from trading_intel.domain.candles import Timeframe
from trading_intel.domain.events import (
    MARKET_CANDLE,
    MARKET_PRICE,
    MARKET_STATUS,
    MarketPricePayload,
    MarketStatusPayload,
)
from trading_intel.events.redis_transport import RedisEventBus

pytestmark = pytest.mark.integration

START = datetime(2026, 1, 1, tzinfo=UTC)
EMAIL = "owner@example.test"
PASSWORD = "a-long-test-password"
ORIGIN = "http://127.0.0.1:3000"
PROTECTED = [
    "/api/v1/instruments",
    "/api/v1/signals",
    "/api/v1/paper-trading/positions",
    "/api/v1/paper-trading/summary",
    "/api/v1/paper-trading/trades?account=demo",
    "/api/v1/auth/me",
    "/api/v1/market/candles?provider=binance_spot&instrument_id=1&timeframe=1m",
    "/api/v1/market/price?provider=binance_spot&instrument_id=1",
    "/api/v1/market/status",
    "/api/v1/market/gaps",
]


@pytest.fixture
def api(clean_database: None) -> Iterator[TestClient]:
    asyncio.run(_flush_redis())
    settings = make_settings(owner_email=EMAIL, owner_password=PASSWORD)
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        yield client


async def _flush_redis() -> None:
    client: Redis = Redis.from_url(make_settings().redis_url.get_secret_value())
    await client.flushdb()
    await client.aclose()


def login(api: TestClient) -> None:
    response = api.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert response.status_code == 200, response.text


async def _seed_candles(count: int) -> tuple[int, int]:
    engine = create_engine(make_settings().ingest_database_url)
    listed = await ReferenceRepository(engine).provider_instruments("binance_spot")
    provider_id, instrument_id = listed[0].provider_id, listed[0].instrument.id
    await CandleRepository(engine).insert(
        [
            make_candle(provider_id, instrument_id, Timeframe.M1, START + timedelta(minutes=m))
            for m in range(count)
        ]
    )
    await engine.dispose()
    return provider_id, instrument_id


async def _publish(publish: Any) -> None:
    client: Redis = Redis.from_url(make_settings().redis_url.get_secret_value())
    await publish(RedisEventBus(client, SystemClock()))
    await client.aclose()


@pytest.mark.parametrize("path", PROTECTED)
def test_market_endpoints_reject_anonymous_requests(api: TestClient, path: str) -> None:
    response = api.get(path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


def test_health_stays_open_without_login(api: TestClient) -> None:
    response = api.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["ready"] is True


def test_login_sets_a_protected_cookie(api: TestClient) -> None:
    response = api.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert api.get("/api/v1/auth/me").json()["email"] == EMAIL


def test_production_cookies_are_secure(clean_database: None) -> None:
    settings = make_settings(owner_email=EMAIL, owner_password=PASSWORD, app_env="production")
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        response = client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert "secure" in response.headers["set-cookie"].lower()


def test_wrong_password_is_refused_and_audited(api: TestClient) -> None:
    response = api.post("/api/v1/auth/login", json={"email": EMAIL, "password": "wrong"})
    assert response.status_code == 401
    assert "not_authenticated" in response.text
    login(api)

    async def actions() -> list[str]:
        connection = await asyncpg.connect(SUPERUSER_URL)
        rows = await connection.fetch("SELECT action FROM audit_log ORDER BY occurred_at")
        await connection.close()
        return [row["action"] for row in rows]

    assert asyncio.run(actions()) == ["owner_created", "login_failed", "login"]


def test_stored_password_is_a_hash(api: TestClient) -> None:
    async def stored() -> str:
        connection = await asyncpg.connect(SUPERUSER_URL)
        value: str = await connection.fetchval("SELECT password_hash FROM users")
        await connection.close()
        return value

    value = asyncio.run(stored())
    assert PASSWORD not in value
    assert value.startswith("$argon2")


def test_login_is_rate_limited(api: TestClient) -> None:
    for _ in range(5):
        api.post("/api/v1/auth/login", json={"email": EMAIL, "password": "wrong"})
    response = api.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert response.status_code == 429


def test_logout_ends_the_session(api: TestClient) -> None:
    login(api)
    api.post("/api/v1/auth/logout")
    assert api.get("/api/v1/auth/me").status_code == 401


def test_instruments_list_providers_and_flags_synthetic(api: TestClient) -> None:
    login(api)
    body = api.get("/api/v1/instruments").json()
    assert {item["provider"] for item in body} == {"binance_spot", "binance_usdm", "synthetic"}
    assert all(item["is_synthetic"] == (item["provider"] == "synthetic") for item in body)


def test_candles_page_backwards_with_strings_utc_and_origin(api: TestClient) -> None:
    _, instrument_id = asyncio.run(_seed_candles(5))
    login(api)
    url = f"/api/v1/market/candles?provider=binance_spot&instrument_id={instrument_id}&timeframe=1m"
    first = api.get(f"{url}&limit=2").json()
    assert [c["open_time"] for c in first["items"]] == [
        "2026-01-01T00:03:00Z",
        "2026-01-01T00:04:00Z",
    ]
    assert isinstance(first["items"][0]["close"], str)
    assert first["items"][0]["data_origin"] == "backfill"

    second = api.get(f"{url}&limit=2&before={first['next_before']}").json()
    assert [c["open_time"] for c in second["items"]] == [
        "2026-01-01T00:01:00Z",
        "2026-01-01T00:02:00Z",
    ]
    last = api.get(f"{url}&limit=2&before={second['next_before']}").json()
    assert len(last["items"]) == 1
    assert last["next_before"] is None


@pytest.mark.parametrize(
    "query",
    [
        "provider=binance_spot&instrument_id=1&timeframe=2m",
        "provider=binance_spot&instrument_id=0&timeframe=1m",
        "provider=binance_spot&instrument_id=1&timeframe=1m&limit=0",
        "provider=binance_spot&instrument_id=1&timeframe=1m&limit=1001",
        "provider=binance_spot&instrument_id=1&timeframe=1m&before=not-a-date",
        "provider=binance_spot&instrument_id=1%20OR%201=1&timeframe=1m",
    ],
)
def test_bad_input_is_rejected_with_the_error_structure(api: TestClient, query: str) -> None:
    login(api)
    response = api.get(f"/api/v1/market/candles?{query}")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_unknown_provider_is_not_found(api: TestClient) -> None:
    login(api)
    response = api.get("/api/v1/market/candles?provider=nope&instrument_id=1&timeframe=1m")
    assert response.status_code == 404


def test_price_is_null_and_stale_when_nothing_is_held(api: TestClient) -> None:
    login(api)
    body = api.get("/api/v1/market/price?provider=binance_spot&instrument_id=1").json()
    assert body["bid"] is None
    assert body["stale"] is True


def price_payload(at: datetime) -> MarketPricePayload:
    return MarketPricePayload(
        provider="binance_spot", instrument_id=1, bid="100.1", ask="100.2", received_at=at
    )


def test_fresh_price_is_current_and_an_old_one_is_flagged(api: TestClient) -> None:
    login(api)
    topic = f"{MARKET_PRICE}:binance_spot:1"
    url = "/api/v1/market/price?provider=binance_spot&instrument_id=1"

    asyncio.run(
        _publish(
            lambda bus: bus.publish_latest(
                topic, MARKET_PRICE, DataOrigin.LIVE, price_payload(datetime.now(UTC))
            )
        )
    )
    fresh = api.get(url).json()
    assert fresh["bid"] == "100.1"
    assert fresh["stale"] is False

    old = datetime.now(UTC) - timedelta(seconds=30)
    asyncio.run(
        _publish(
            lambda bus: bus.publish_latest(topic, MARKET_PRICE, DataOrigin.LIVE, price_payload(old))
        )
    )
    assert api.get(url).json()["stale"] is True


def test_status_reports_a_missing_ingestor_as_disconnected(api: TestClient) -> None:
    login(api)
    body = api.get("/api/v1/market/status").json()
    assert body["usable"] is False
    assert body["feeds"][0]["state"] == "DISCONNECTED"
    assert body["feeds"][0]["reasons"] == ["ingestor is not reporting"]


def test_status_is_usable_only_when_every_feed_is_healthy(api: TestClient) -> None:
    login(api)

    async def publish_all(bus: RedisEventBus) -> None:
        for code in ("binance_spot", "binance_usdm"):
            await bus.publish_latest(
                f"{MARKET_STATUS}:{code}",
                MARKET_STATUS,
                DataOrigin.LIVE,
                MarketStatusPayload(provider=code, state="HEALTHY", reasons=[]),
            )

    asyncio.run(_publish(publish_all))
    assert api.get("/api/v1/market/status").json()["usable"] is True


def test_paper_summary_is_labelled_simulated_and_shows_no_fake_results(api: TestClient) -> None:
    login(api)
    body = api.get("/api/v1/paper-trading/summary").json()
    assert body["simulated"] is True
    assert body["starting_balance"].startswith("10000")
    assert body["win_rate"] is None
    assert body["expectancy_r"] is None
    assert api.get("/api/v1/signals").json() == []
    assert api.get("/api/v1/paper-trading/positions").json() == []


def test_the_demo_bot_reports_its_own_100_usdt_account(api: TestClient) -> None:
    """D044: the demo bot's account is separate from the tested strategies' account."""
    login(api)
    demo = api.get("/api/v1/paper-trading/summary?account=demo").json()
    assert demo["simulated"] is True
    assert demo["account"] == "demo"
    assert Decimal(demo["starting_balance"]) == 100
    assert Decimal(demo["equity"]) == 100
    assert api.get("/api/v1/paper-trading/summary").json()["account"] == "paper"
    assert api.get("/api/v1/paper-trading/trades?account=demo").json() == []
    assert api.get("/api/v1/signals?account=demo").json() == []
    assert api.get("/api/v1/paper-trading/summary?account=live").status_code == 422


def test_the_money_plan_reports_its_own_1000_usdt_account_and_limits(api: TestClient) -> None:
    """D045: the API may create the account first, so it must give it the plan's limits."""
    login(api)
    plan = api.get("/api/v1/paper-trading/summary?account=portfolio").json()
    assert plan["account"] == "portfolio"
    assert Decimal(plan["starting_balance"]) == 1000
    assert Decimal(plan["day_start_equity"]) == 1000
    assert Decimal(plan["open_risk"]) == 0
    assert Decimal(plan["max_open_risk"]) == Decimal("0.03")
    assert Decimal(plan["daily_profit_stop"]) == Decimal("0.03")
    demo = api.get("/api/v1/paper-trading/summary?account=demo").json()
    assert demo["max_open_risk"] is None and demo["daily_profit_stop"] is None
    assert api.get("/api/v1/paper-trading/trades?account=portfolio").json() == []


def test_no_route_can_place_a_trade(api: TestClient) -> None:
    routes = {
        (method, path)
        for path, methods in api.app.openapi()["paths"].items()  # type: ignore[attr-defined]
        for method in methods
    }
    writes = {path for method, path in routes if method != "get"}
    assert writes == {
        "/api/v1/auth/login",
        "/api/v1/auth/logout",
        "/api/v1/auth/ws-ticket",
        # Runs a Kronos forecast and stores it. Forecasts cannot reach orders (D040).
        "/api/v1/forecasts/analyse",
    }


def test_gaps_are_listed(api: TestClient) -> None:
    provider_id, instrument_id = asyncio.run(_seed_candles(1))

    async def record() -> None:
        engine = create_engine(make_settings().ingest_database_url)
        await GapRepository(engine).record(
            provider_id,
            instrument_id,
            Timeframe.M1,
            START,
            START + timedelta(minutes=2),
            "ingest_failure",
        )
        await engine.dispose()

    asyncio.run(record())
    login(api)
    [gap] = api.get("/api/v1/market/gaps?provider=binance_spot").json()["items"]
    assert gap["state"] == "detected"


def ticket(api: TestClient) -> str:
    login(api)
    return str(api.post("/api/v1/auth/ws-ticket").json()["ticket"])


def test_websocket_rejects_a_bad_origin(api: TestClient) -> None:
    value = ticket(api)
    with (
        pytest.raises(WebSocketDisconnect) as refused,
        api.websocket_connect(f"/api/v1/ws?ticket={value}", headers={"origin": "http://evil.test"}),
    ):
        pass
    assert refused.value.code == 4403


def test_websocket_rejects_a_missing_origin(api: TestClient) -> None:
    value = ticket(api)
    with (
        pytest.raises(WebSocketDisconnect) as refused,
        api.websocket_connect(f"/api/v1/ws?ticket={value}"),
    ):
        pass
    assert refused.value.code == 4403


def test_websocket_rejects_a_bad_ticket(api: TestClient) -> None:
    with (
        pytest.raises(WebSocketDisconnect) as refused,
        api.websocket_connect("/api/v1/ws?ticket=forged", headers={"origin": ORIGIN}),
    ):
        pass
    assert refused.value.code == 4401


def test_a_session_cookie_is_not_a_websocket_ticket(api: TestClient) -> None:
    login(api)
    session = api.cookies.get("ati_session")
    with (
        pytest.raises(WebSocketDisconnect) as refused,
        api.websocket_connect(f"/api/v1/ws?ticket={session}", headers={"origin": ORIGIN}),
    ):
        pass
    assert refused.value.code == 4401


@pytest.fixture
async def server(clean_database: None) -> AsyncIterator[str]:
    """A real uvicorn server, because that is what the dashboard connects to."""
    await _flush_redis()
    settings = make_settings(owner_email=EMAIL, owner_password=PASSWORD)
    config = uvicorn.Config(create_app(settings), host="127.0.0.1", port=0, log_config=None)
    instance = uvicorn.Server(config)
    running = asyncio.create_task(instance.serve())
    while not instance.started:  # noqa: ASYNC110
        await asyncio.sleep(0.01)
    port = instance.servers[0].sockets[0].getsockname()[1]
    yield f"127.0.0.1:{port}"
    instance.should_exit = True
    await running


async def real_ticket(address: str) -> str:
    async with httpx.AsyncClient(base_url=f"http://{address}") as client:
        response = await client.post(
            "/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD}
        )
        assert response.status_code == 200
        return str((await client.post("/api/v1/auth/ws-ticket")).json()["ticket"])


def socket_url(address: str, value: str) -> str:
    return f"ws://{address}/api/v1/ws?ticket={value}"


async def test_a_ticket_cannot_be_used_twice(server: str) -> None:
    url = socket_url(server, await real_ticket(server))
    async with websockets.connect(url, origin=ORIGIN):
        pass
    with pytest.raises(InvalidStatus):
        async with websockets.connect(url, origin=ORIGIN):
            pass


async def test_subscribed_client_receives_a_live_event(server: str) -> None:
    topic = f"{MARKET_CANDLE}:binance_spot:1:1m"
    url = socket_url(server, await real_ticket(server))
    async with websockets.connect(url, origin=ORIGIN) as socket:
        await socket.send(json.dumps({"type": "subscribe", "topics": [topic]}))
        assert json.loads(await socket.recv()) == {"type": "subscribed", "topics": [topic]}

        async def send(bus: RedisEventBus) -> None:
            await bus.publish_latest(
                topic, MARKET_CANDLE, DataOrigin.LIVE, price_payload(datetime.now(UTC))
            )

        await _publish(send)
        event = json.loads(await asyncio.wait_for(socket.recv(), 3))
    assert event["event_type"] == MARKET_CANDLE
    assert event["data_origin"] == "live"
    assert event["seq"] >= 1


async def test_events_for_other_topics_are_not_delivered(server: str) -> None:
    wanted = f"{MARKET_PRICE}:binance_spot:1"
    other = f"{MARKET_PRICE}:binance_spot:2"
    url = socket_url(server, await real_ticket(server))
    async with websockets.connect(url, origin=ORIGIN) as socket:
        await socket.send(json.dumps({"type": "subscribe", "topics": [wanted]}))
        await socket.recv()

        async def send(bus: RedisEventBus) -> None:
            payload = price_payload(datetime.now(UTC))
            await bus.publish_latest(other, MARKET_PRICE, DataOrigin.LIVE, payload)
            await bus.publish_latest(wanted, MARKET_PRICE, DataOrigin.LIVE, payload)

        await _publish(send)
        event = json.loads(await asyncio.wait_for(socket.recv(), 3))
    assert event["seq"] == 1
    assert event["payload"]["instrument_id"] == 1
