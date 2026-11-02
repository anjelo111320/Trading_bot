"""Public REST access: GET only, on an allow-list, within a self-imposed weight cap."""

import asyncio
import random
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import httpx
import structlog

from trading_intel.core.clock import Clock
from trading_intel.core.errors import ProviderError, ProviderHaltError

log = structlog.get_logger(__name__)

Sleep = Callable[[float], Awaitable[None]]

MAX_ATTEMPTS = 5
USED_WEIGHT_HEADER = "X-MBX-USED-WEIGHT-1M"
HALT_MESSAGES = {
    403: "Binance refused the request (WAF or security block)",
    418: "Binance banned this IP for ignoring rate limits",
    451: "Binance refuses this location. Do not retry from another host",
}


class WeightLimiter:
    """Tracks request weight per calendar minute, which is how Binance counts it."""

    def __init__(self, cap_per_minute: int, clock: Clock, sleep: Sleep) -> None:
        self.cap = cap_per_minute
        self._clock = clock
        self._sleep = sleep
        self._minute = -1
        self.used = 0

    def _current_minute(self) -> tuple[int, float]:
        epoch = self._clock.now().timestamp()
        return int(epoch // 60), 60 - epoch % 60

    async def acquire(self, weight: int) -> None:
        minute, remaining = self._current_minute()
        if minute != self._minute:
            self._minute, self.used = minute, 0
        if self.used + weight > self.cap:
            await self._sleep(remaining)
            self._minute, _ = self._current_minute()
            self.used = 0
        self.used += weight

    def observe(self, used_by_provider: int) -> None:
        """Binance's count is the true one, and also includes other clients on this IP."""
        self.used = max(self.used, used_by_provider)

    def reduce_cap(self) -> None:
        self.cap = max(self.cap // 2, 1)


class BinanceRestClient:
    def __init__(
        self,
        base_url: str,
        allowed_paths: frozenset[str],
        cap_per_minute: int,
        clock: Clock,
        *,
        http: httpx.AsyncClient | None = None,
        sleep: Sleep = asyncio.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self._allowed_paths = allowed_paths
        self._http = http or httpx.AsyncClient(base_url=base_url, timeout=15)
        self._sleep = sleep
        self._rng = rng or random.Random()  # noqa: S311
        self.limiter = WeightLimiter(cap_per_minute, clock, sleep)
        self._halt: str | None = None

    async def close(self) -> None:
        await self._http.aclose()

    async def get(self, path: str, params: Mapping[str, Any], weight: int) -> Any:
        """GET a public path. There is no method for any other verb."""
        if path not in self._allowed_paths:
            raise ProviderError(f"path not on the allow-list: {path}")
        if self._halt:
            raise ProviderHaltError(self._halt)

        for attempt in range(MAX_ATTEMPTS):
            await self.limiter.acquire(weight)
            try:
                response = await self._http.get(path, params=dict(params))
            except httpx.TransportError as error:
                log.warning("provider_transport_error", path=path, error=type(error).__name__)
                await self._backoff(attempt)
                continue

            self._observe_weight(response)
            status = response.status_code
            if status == 200:
                return response.json()
            if status in HALT_MESSAGES:
                self._halt = HALT_MESSAGES[status]
                log.error("provider_halted", path=path, status=status)
                raise ProviderHaltError(self._halt)
            if status == 429:
                self.limiter.reduce_cap()
                await self._sleep(float(response.headers.get("Retry-After", 60)))
                continue
            if status >= 500:
                await self._backoff(attempt)
                continue
            raise ProviderError(f"{path} returned {status}: {response.text[:200]}")
        raise ProviderError(f"{path} failed after {MAX_ATTEMPTS} attempts")

    def _observe_weight(self, response: httpx.Response) -> None:
        used = response.headers.get(USED_WEIGHT_HEADER)
        if used is not None and used.isdigit():
            self.limiter.observe(int(used))

    async def _backoff(self, attempt: int) -> None:
        delay: float = min(2**attempt, 30)
        await self._sleep(delay + self._rng.uniform(0, delay / 2))
