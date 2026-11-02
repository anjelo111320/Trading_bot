"""Liveness and readiness. Open without login, and reveals no configuration."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends

from trading_intel.api.container import Container, Probe, get_container
from trading_intel.api.schemas.health import DependencyHealth, HealthResponse
from trading_intel.core.settings import TRADING_MODE

router = APIRouter(prefix="/api/v1/health", tags=["health"])

PROBE_TIMEOUT_SECONDS = 2


async def _check(name: str, probe: Probe) -> DependencyHealth:
    try:
        await asyncio.wait_for(probe(), PROBE_TIMEOUT_SECONDS)
    except TimeoutError:
        return DependencyHealth(name=name, ok=False, detail="timed out")
    except Exception as error:
        return DependencyHealth(name=name, ok=False, detail=type(error).__name__)
    return DependencyHealth(name=name, ok=True)


@router.get("", response_model=HealthResponse)
async def health(container: Annotated[Container, Depends(get_container)]) -> HealthResponse:
    checks = [_check(name, probe) for name, probe in container.probes.items()]
    dependencies = list(await asyncio.gather(*checks))
    return HealthResponse(
        ready=all(item.ok for item in dependencies),
        trading_mode=TRADING_MODE,
        checked_at=container.clock.now(),
        dependencies=dependencies,
    )
