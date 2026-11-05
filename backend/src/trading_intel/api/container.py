"""Services shared by request handlers, created once and injected."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from fastapi import Request
from starlette.requests import HTTPConnection

from trading_intel.core.clock import Clock
from trading_intel.core.settings import Settings

if TYPE_CHECKING:
    from trading_intel.api.auth import LoginLimiter, TicketLedger, TokenSigner
    from trading_intel.api.forecast_jobs import AnalysisJobs
    from trading_intel.database.repositories.accounts import AuditRepository, UserRepository
    from trading_intel.database.repositories.candles import CandleRepository
    from trading_intel.database.repositories.forecasts import ForecastRepository
    from trading_intel.database.repositories.news import NewsRepository
    from trading_intel.database.repositories.operations import (
        GapRepository,
        RuleRepository,
        SnapshotRepository,
    )
    from trading_intel.database.repositories.paper import PaperRepository
    from trading_intel.database.repositories.reference import ReferenceRepository
    from trading_intel.database.repositories.signals import SignalRepository
    from trading_intel.events.redis_transport import RedisEventBus
    from trading_intel.forecasting.service import ForecastService
    from trading_intel.monitoring.coverage import CoverageService

Probe = Callable[[], Awaitable[None]]


@dataclass
class Container:
    settings: Settings
    clock: Clock
    probes: dict[str, Probe] = field(default_factory=dict)
    signer: TokenSigner = field(default=None)  # type: ignore[assignment]
    limiter: LoginLimiter = field(default=None)  # type: ignore[assignment]
    tickets: TicketLedger = field(default=None)  # type: ignore[assignment]
    users: UserRepository = field(default=None)  # type: ignore[assignment]
    audit: AuditRepository = field(default=None)  # type: ignore[assignment]
    reference: ReferenceRepository = field(default=None)  # type: ignore[assignment]
    candles: CandleRepository = field(default=None)  # type: ignore[assignment]
    gaps: GapRepository = field(default=None)  # type: ignore[assignment]
    rules: RuleRepository = field(default=None)  # type: ignore[assignment]
    snapshots: SnapshotRepository = field(default=None)  # type: ignore[assignment]
    bus: RedisEventBus = field(default=None)  # type: ignore[assignment]
    coverage: CoverageService = field(default=None)  # type: ignore[assignment]
    signals: SignalRepository = field(default=None)  # type: ignore[assignment]
    paper: PaperRepository = field(default=None)  # type: ignore[assignment]
    news: NewsRepository = field(default=None)  # type: ignore[assignment]
    forecasts: ForecastRepository = field(default=None)  # type: ignore[assignment]
    forecaster: ForecastService = field(default=None)  # type: ignore[assignment]
    analyses: AnalysisJobs = field(default=None)  # type: ignore[assignment]


def get_container(request: HTTPConnection) -> Container:
    container: Container = request.app.state.container
    return container


__all__ = ["Container", "Probe", "Request", "get_container"]
