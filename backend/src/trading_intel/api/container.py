"""Services shared by request handlers, created once and injected."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from fastapi import Request

from trading_intel.core.clock import Clock
from trading_intel.core.settings import Settings

Probe = Callable[[], Awaitable[None]]


@dataclass
class Container:
    settings: Settings
    clock: Clock
    probes: dict[str, Probe] = field(default_factory=dict)


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container
