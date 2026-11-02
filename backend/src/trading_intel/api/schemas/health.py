from typing import Literal

from pydantic import BaseModel

from trading_intel.core.clock import UtcDatetime
from trading_intel.core.settings import TradingMode


class DependencyHealth(BaseModel):
    name: str
    ok: bool
    detail: str | None = None


class HealthResponse(BaseModel):
    live: Literal[True] = True
    ready: bool
    trading_mode: TradingMode
    checked_at: UtcDatetime
    dependencies: list[DependencyHealth]
