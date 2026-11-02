"""Application factory. Dependencies are passed in, so tests need no real services."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import uuid7

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from trading_intel.api.auth import LoginLimiter, TicketLedger, TokenSigner, hash_password
from trading_intel.api.container import Container
from trading_intel.api.errors import ErrorResponse, install_error_handlers
from trading_intel.api.routers import auth, health, market
from trading_intel.api.websocket import gateway
from trading_intel.core.clock import Clock, SystemClock
from trading_intel.core.settings import Settings
from trading_intel.database.engine import create_engine, ping
from trading_intel.database.repositories.accounts import AuditRepository, UserRepository
from trading_intel.database.repositories.candles import CandleRepository
from trading_intel.database.repositories.operations import (
    EventRepository,
    GapRepository,
    RuleRepository,
    SnapshotRepository,
)
from trading_intel.database.repositories.reference import ReferenceRepository
from trading_intel.events.redis_transport import RedisEventBus
from trading_intel.monitoring.coverage import CoverageService

REQUEST_ID_HEADER = "X-Request-ID"

log = structlog.get_logger(__name__)


def build_services(
    settings: Settings, clock: Clock | None = None
) -> tuple[Container, Callable[[], Awaitable[None]]]:
    clock = clock or SystemClock()
    engine = create_engine(settings.database_url)
    redis: Redis = Redis.from_url(settings.redis_url.get_secret_value())

    async def check_database() -> None:
        await ping(engine)

    async def check_redis() -> None:
        await redis.ping()

    async def close() -> None:
        await redis.aclose()
        await engine.dispose()

    reference = ReferenceRepository(engine)
    candles = CandleRepository(engine)
    gaps = GapRepository(engine)
    snapshots = SnapshotRepository(engine)
    container = Container(
        settings=settings,
        clock=clock,
        probes={"database": check_database, "redis": check_redis},
        signer=TokenSigner(settings.app_secret_key.get_secret_value(), clock),
        limiter=LoginLimiter(clock),
        tickets=TicketLedger(clock),
        users=UserRepository(engine),
        audit=AuditRepository(engine),
        reference=reference,
        candles=candles,
        gaps=gaps,
        rules=RuleRepository(engine),
        snapshots=snapshots,
        bus=RedisEventBus(redis, clock),
        coverage=CoverageService(reference, candles, gaps, snapshots, EventRepository(engine)),
    )
    return container, close


async def ensure_owner(container: Container) -> None:
    """Create the single owner from the environment, once."""
    settings = container.settings
    password = settings.owner_password.get_secret_value()
    if not settings.owner_email or not password:
        return
    if await container.users.count() == 0:
        await container.users.create_owner(settings.owner_email, hash_password(password))
        await container.audit.record("system", "owner_created", "user")
        log.info("owner_created")


def create_app(settings: Settings, container: Container | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        close = None
        if container is None:
            app.state.container, close = build_services(settings)
            await ensure_owner(app.state.container)
        bus = app.state.container.bus
        pump = None
        if bus is not None:
            pump = asyncio.create_task(gateway.pump_events(app.state.hub, bus.live_events))
        yield
        if pump:
            pump.cancel()
            await asyncio.gather(pump, return_exceptions=True)
        if close:
            await close()

    app = FastAPI(
        title="AI Trading Intelligence",
        version="0.1.0",
        lifespan=lifespan,
        responses={"default": {"model": ErrorResponse}},
    )
    app.state.hub = gateway.Hub()
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
    app.include_router(auth.router)
    app.include_router(market.router)
    app.include_router(gateway.router)
    return app
