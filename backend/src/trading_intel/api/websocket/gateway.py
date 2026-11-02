"""Fans live events from Redis out to browsers.

Each client has a bounded queue. Latest-value topics collapse for a slow client. A closed
candle is never dropped silently: if it cannot be queued, the client is told to resync.
Every API worker subscribes to Redis itself, so this also works with several workers.
"""

import asyncio
import contextlib
import json
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable
from typing import Annotated, Final

import structlog
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from trading_intel.api.container import get_container
from trading_intel.domain.events import MARKET_PRICE

log = structlog.get_logger(__name__)

router = APIRouter()

CLOSE_BAD_TICKET: Final = 4401
CLOSE_BAD_ORIGIN: Final = 4403
QUEUE_LIMIT: Final = 256
HEARTBEAT_SECONDS: Final = 15.0
MAX_TOPICS: Final = 64


def collapses(topic: str) -> bool:
    return topic.startswith(MARKET_PRICE) or topic.startswith("market.status")


def is_closed_candle(body: str) -> bool:
    return '"is_closed":true' in body


class ClientQueue:
    """Keeps at most one entry per collapsing topic, and a bounded list of the rest."""

    def __init__(self, limit: int = QUEUE_LIMIT) -> None:
        self._limit = limit
        self._items: OrderedDict[object, str] = OrderedDict()
        self._next = 0
        self._ready = asyncio.Event()
        self.resync: list[str] = []

    def put(self, topic: str, body: str) -> None:
        if collapses(topic):
            self._items[topic] = body
            self._items.move_to_end(topic)
        elif len(self._items) >= self._limit:
            if is_closed_candle(body) and topic not in self.resync:
                self.resync.append(topic)
            # A forming update has no lasting value, so it can simply be dropped.
        else:
            self._next += 1
            self._items[self._next] = body
        self._ready.set()

    async def get(self) -> str:
        while True:
            if self.resync:
                return json.dumps({"type": "resync", "topic": self.resync.pop(0)})
            if self._items:
                _, body = self._items.popitem(last=False)
                return body
            self._ready.clear()
            await self._ready.wait()


class Hub:
    """Tracks connected clients in this worker and delivers events to them."""

    def __init__(self) -> None:
        self._clients: dict[ClientQueue, set[str]] = {}

    def add(self, queue: ClientQueue) -> None:
        self._clients[queue] = set()

    def remove(self, queue: ClientQueue) -> None:
        self._clients.pop(queue, None)

    def subscribe(self, queue: ClientQueue, topics: list[str]) -> None:
        self._clients[queue].update(topics)

    def deliver(self, topic: str, body: str) -> None:
        for queue, topics in self._clients.items():
            if topic in topics:
                queue.put(topic, body)


async def pump_events(hub: Hub, events: Callable[[], AsyncIterator[tuple[str, str]]]) -> None:
    """Copy Redis events to the hub, reconnecting if Redis goes away."""
    while True:
        try:
            async for topic, body in events():
                hub.deliver(topic, body)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            log.warning("event_pump_failed", error=type(error).__name__)
            await asyncio.sleep(1)


async def _send_loop(websocket: WebSocket, queue: ClientQueue) -> None:
    while True:
        try:
            async with asyncio.timeout(HEARTBEAT_SECONDS):
                body = await queue.get()
        except TimeoutError:
            body = json.dumps({"type": "heartbeat"})
        await websocket.send_text(body)


async def _receive_loop(websocket: WebSocket, hub: Hub, queue: ClientQueue) -> None:
    while True:
        message = await websocket.receive_json()
        if not isinstance(message, dict) or message.get("type") != "subscribe":
            continue
        topics = [t for t in message.get("topics", []) if isinstance(t, str)][:MAX_TOPICS]
        hub.subscribe(queue, topics)
        await websocket.send_text(json.dumps({"type": "subscribed", "topics": topics}))


@router.websocket("/api/v1/ws")
async def gateway(websocket: WebSocket, ticket: Annotated[str, Query()] = "") -> None:
    services = get_container(websocket)
    origin = websocket.headers.get("origin")
    if origin not in services.settings.cors_origins:
        await websocket.close(CLOSE_BAD_ORIGIN)
        return
    claims = services.signer.read(ticket, "websocket")
    if claims is None or not services.tickets.consume(claims[1]):
        await websocket.close(CLOSE_BAD_TICKET)
        return

    await websocket.accept()
    hub: Hub = websocket.app.state.hub
    queue = ClientQueue()
    hub.add(queue)
    sender = asyncio.create_task(_send_loop(websocket, queue))
    receiver = asyncio.create_task(_receive_loop(websocket, hub, queue))
    try:
        done, _ = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            with contextlib.suppress(WebSocketDisconnect, ValueError, RuntimeError):
                task.result()
    finally:
        hub.remove(queue)
        for task in (sender, receiver):
            task.cancel()
        await asyncio.gather(sender, receiver, return_exceptions=True)
