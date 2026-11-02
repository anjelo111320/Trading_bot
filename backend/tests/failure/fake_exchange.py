"""A real local WebSocket server that misbehaves on command."""

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import websockets
from websockets.asyncio.server import ServerConnection

Behaviour = Callable[[ServerConnection, int], Awaitable[None]]


@dataclass
class FakeExchange:
    behaviour: Behaviour
    connections: int = 0
    open_now: int = 0
    max_open: int = 0
    paths: list[str] = field(default_factory=list)
    port: int = 0

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.port}"

    async def handle(self, connection: ServerConnection) -> None:
        self.connections += 1
        self.open_now += 1
        self.max_open = max(self.max_open, self.open_now)
        self.paths.append(connection.request.path if connection.request else "")
        try:
            await self.behaviour(connection, self.connections)
        finally:
            self.open_now -= 1


@asynccontextmanager
async def running(behaviour: Behaviour, **options: Any) -> AsyncIterator[FakeExchange]:
    exchange = FakeExchange(behaviour)
    async with websockets.serve(exchange.handle, "127.0.0.1", 0, **options) as server:
        exchange.port = next(iter(server.sockets)).getsockname()[1]
        yield exchange


async def stay_open(connection: ServerConnection) -> None:
    await connection.wait_closed()


async def send_json(connection: ServerConnection, value: object) -> None:
    await connection.send(json.dumps(value))


async def collect[T](iterator: AsyncIterator[T], count: int, limit: float = 5) -> list[T]:
    """Take `count` items, failing rather than hanging if they never come."""
    items: list[T] = []
    async with asyncio.timeout(limit):
        async for item in iterator:
            items.append(item)
            if len(items) == count:
                break
    return items
