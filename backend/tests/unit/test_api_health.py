from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI

from tests.conftest import make_settings
from trading_intel.api.app import REQUEST_ID_HEADER, create_app
from trading_intel.api.container import Container
from trading_intel.core.clock import FixedClock
from trading_intel.core.errors import NotFoundError
from trading_intel.entrypoints.export_openapi import OPENAPI_PATH, render_openapi

NOW = datetime(2026, 1, 1, tzinfo=UTC)


async def healthy() -> None:
    return None


async def broken() -> None:
    raise ConnectionError("password=secret-value")


def build(probes: dict[str, object] | None = None) -> FastAPI:
    settings = make_settings()
    container = Container(settings, FixedClock(NOW), probes or {"database": healthy})  # type: ignore[arg-type]
    return create_app(settings, container)


def client(app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_health_is_ready_when_dependencies_are_up() -> None:
    async with client(build({"database": healthy, "redis": healthy})) as http:
        response = await http.get("/api/v1/health")
    body = response.json()
    assert response.status_code == 200
    assert body["live"] is True
    assert body["ready"] is True
    assert body["trading_mode"] == "paper"
    assert body["checked_at"] == "2026-01-01T00:00:00Z"


async def test_health_reports_a_failed_dependency_without_leaking_detail() -> None:
    async with client(build({"database": healthy, "redis": broken})) as http:
        response = await http.get("/api/v1/health")
    body = response.json()
    assert response.status_code == 200
    assert body["live"] is True
    assert body["ready"] is False
    assert {"name": "redis", "ok": False, "detail": "ConnectionError"} in body["dependencies"]
    assert "secret-value" not in response.text


async def test_unknown_route_uses_the_error_structure() -> None:
    async with client(build()) as http:
        response = await http.get("/api/v1/nope")
    error = response.json()["error"]
    assert response.status_code == 404
    assert error["code"] == "not_found"
    assert error["request_id"] == response.headers[REQUEST_ID_HEADER]


async def test_app_error_uses_the_error_structure() -> None:
    app = build()

    @app.get("/raises")
    async def raises() -> None:
        raise NotFoundError("no such instrument")

    async with client(app) as http:
        response = await http.get("/raises")
    assert response.status_code == 404
    assert response.json()["error"]["message"] == "no such instrument"


async def test_unexpected_error_hides_its_detail() -> None:
    app = build()

    @app.get("/crashes")
    async def crashes() -> None:
        raise RuntimeError("internal secret detail")

    async with client(app) as http:
        response = await http.get("/crashes")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "internal secret detail" not in response.text


@pytest.mark.parametrize(
    ("origin", "allowed"),
    [("http://127.0.0.1:3000", True), ("http://evil.example", False)],
)
async def test_only_configured_origins_pass_cors(origin: str, allowed: bool) -> None:
    async with client(build()) as http:
        response = await http.get("/api/v1/health", headers={"Origin": origin})
    assert ("access-control-allow-origin" in response.headers) is allowed


def test_committed_openapi_file_is_current() -> None:
    assert OPENAPI_PATH.read_text() == render_openapi()
