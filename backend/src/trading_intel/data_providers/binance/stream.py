"""A WebSocket link that survives drops, shutdown notices and the 24-hour limit."""

import asyncio
import contextlib
import json
import random
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

import structlog
import websockets

from trading_intel.core.clock import Clock

log = structlog.get_logger(__name__)

ROLLOVER_AFTER_SECONDS = 23 * 3600 + 50 * 60
OVERLAP_SECONDS = 5.0
MIN_CONNECT_SPACING_SECONDS = 1.0  # One a second stays well inside 300 per 5 minutes.
MAX_BACKOFF_SECONDS = 30.0
QUEUE_SIZE = 10_000


class Connection(Protocol):
    async def recv(self) -> str | bytes: ...

    async def close(self) -> None: ...


Connector = Callable[[str], Awaitable[Connection]]


async def connect_websocket(url: str) -> Connection:
    return await websockets.connect(url, open_timeout=10, ping_interval=20, ping_timeout=20)


@dataclass(frozen=True)
class Frame:
    route: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class Connected:
    route: str


@dataclass(frozen=True)
class Disconnected:
    route: str
    reason: str


@dataclass(frozen=True)
class BadFrame:
    route: str
    reason: str


StreamItem = Frame | Connected | Disconnected | BadFrame


class ResilientStream:
    """Yields frames forever, reconnecting as needed.

    Rollover is make-before-break: the new connection opens first and the old one closes
    after a short overlap, so duplicates are possible and losses are not. Consumers are
    idempotent, so duplicates are harmless.
    """

    def __init__(
        self,
        route: str,
        url: str,
        clock: Clock,
        *,
        connector: Connector = connect_websocket,
        rollover_after: float = ROLLOVER_AFTER_SECONDS,
        overlap: float = OVERLAP_SECONDS,
        min_spacing: float = MIN_CONNECT_SPACING_SECONDS,
        rng: random.Random | None = None,
    ) -> None:
        self._route = route
        self._url = url
        self._clock = clock
        self._connector = connector
        self._rollover_after = rollover_after
        self._overlap = overlap
        self._min_spacing = min_spacing
        self._rng = rng or random.Random()  # noqa: S311
        self._last_attempt: float | None = None

    async def items(self) -> AsyncIterator[StreamItem]:
        queue: asyncio.Queue[StreamItem] = asyncio.Queue(maxsize=QUEUE_SIZE)
        supervisor = asyncio.create_task(self._supervise(queue))
        try:
            while True:
                if supervisor.done():
                    supervisor.result()
                yield await queue.get()
        finally:
            supervisor.cancel()
            await asyncio.gather(supervisor, return_exceptions=True)

    async def _open(self, queue: asyncio.Queue[StreamItem]) -> Connection:
        attempt = 0
        while True:
            await self._space_attempts()
            try:
                connection = await self._connector(self._url)
            except (OSError, TimeoutError, websockets.WebSocketException) as error:
                reason = f"connect failed: {type(error).__name__}"
                log.warning("stream_connect_failed", route=self._route, error=type(error).__name__)
                await queue.put(Disconnected(self._route, reason))
                delay = min(2.0**attempt, MAX_BACKOFF_SECONDS)
                await asyncio.sleep(delay + self._rng.uniform(0, delay / 2))
                attempt += 1
                continue
            await queue.put(Connected(self._route))
            return connection

    async def _space_attempts(self) -> None:
        now = self._clock.monotonic()
        if self._last_attempt is not None:
            wait = self._min_spacing - (now - self._last_attempt)
            if wait > 0:
                await asyncio.sleep(wait)
        self._last_attempt = self._clock.monotonic()

    async def _supervise(self, queue: asyncio.Queue[StreamItem]) -> None:
        tasks: set[asyncio.Task[None]] = set()
        try:
            retiring: tuple[Connection, asyncio.Task[None]] | None = None
            while True:
                connection = await self._open(queue)
                pump = asyncio.create_task(self._pump(connection, queue))
                tasks.add(pump)
                pump.add_done_callback(tasks.discard)
                if retiring:
                    tasks.add(asyncio.create_task(self._retire(*retiring)))
                    retiring = None
                done, _ = await asyncio.wait({pump}, timeout=self._rollover_after)
                if done:
                    await queue.put(Disconnected(self._route, pump.result() or "connection closed"))
                else:
                    log.info("stream_rollover", route=self._route)
                    retiring = (connection, pump)
        finally:
            for task in tasks:
                task.cancel()

    async def _retire(self, connection: Connection, pump: asyncio.Task[None]) -> None:
        await asyncio.sleep(self._overlap)
        pump.cancel()
        await asyncio.gather(pump, return_exceptions=True)
        await connection.close()

    async def _pump(self, connection: Connection, queue: asyncio.Queue[StreamItem]) -> Any:
        """Read until the link ends. Returns the reason, or None for a plain close."""
        try:
            while True:
                try:
                    raw = await connection.recv()
                except websockets.ConnectionClosed as error:
                    return f"connection closed: {error.rcvd.code if error.rcvd else 'no code'}"
                except OSError as error:
                    return f"connection lost: {type(error).__name__}"
                try:
                    payload = json.loads(raw)
                except ValueError:
                    await queue.put(BadFrame(self._route, "invalid_json"))
                    continue
                if not isinstance(payload, dict):
                    await queue.put(BadFrame(self._route, "frame_not_an_object"))
                    continue
                if _is_shutdown(payload):
                    await connection.close()
                    return "server shutdown notice"
                await queue.put(Frame(self._route, payload))
        finally:
            with contextlib.suppress(Exception):
                await connection.close()


def _is_shutdown(payload: dict[str, Any]) -> bool:
    data = payload.get("data")
    inner = data.get("e") if isinstance(data, dict) else None
    return "serverShutdown" in (payload.get("e"), inner)
