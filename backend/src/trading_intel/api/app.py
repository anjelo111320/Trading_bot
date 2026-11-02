"""Application factory. Dependencies are passed in, so tests need no real services."""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import uuid7

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from trading_intel.api.container import Container
from trading_intel.api.errors import ErrorResponse, install_error_handlers
from trading_intel.api.routers import health
from trading_intel.core.clock import SystemClock
from trading_intel.core.settings import Settings
from trading_intel.database.engine import create_engine, ping

REQUEST_ID_HEADER = "X-Request-ID"


def _build_container(settings: Settings) -> tuple[Container, Callable[[], Awaitable[None]]]:
    engine = create_engine(settings.database_url)
    redis: Redis = Redis.from_url(settings.redis_url.get_secret_value())

    async def check_database() -> None:
        await ping(engine)

    async def check_redis() -> None:
        await redis.ping()

    async def close() -> None:
        await redis.aclose()
        await engine.dispose()

    container = Container(
        settings=settings,
        clock=SystemClock(),
        probes={"database": check_database, "redis": check_redis},
    )
    return container, close


def create_app(settings: Settings, container: Container | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if container is not None:
            app.state.container = container
            yield
            return
        app.state.container, close = _build_container(settings)
        yield
        await close()

    app = FastAPI(
        title="AI Trading Intelligence",
        version="0.1.0",
        lifespan=lifespan,
        responses={"default": {"model": ErrorResponse}},
    )
    if container is not None:
        app.state.container = container

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type"],
    )

    @app.middleware("http")
    async def assign_request_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = str(uuid7())
        request.state.request_id = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id)
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        structlog.contextvars.unbind_contextvars("request_id")
        return response

    install_error_handlers(app)
    app.include_router(health.router)
    return app
