import asyncio
import json

from trading_intel.api.websocket.gateway import ClientQueue, Hub

PRICE = "market.price:binance_spot:1"
CANDLE = "market.candle:binance_spot:1:1m"
CLOSED = '{"event_type":"market.candle","payload":{"is_closed":true}}'
FORMING = '{"event_type":"market.candle","payload":{"is_closed":false}}'


async def drain(queue: ClientQueue, count: int) -> list[str]:
    return [await asyncio.wait_for(queue.get(), 1) for _ in range(count)]


async def test_prices_collapse_to_the_latest_for_a_slow_client() -> None:
    queue = ClientQueue()
    for value in ("1", "2", "3"):
        queue.put(PRICE, value)
    assert await drain(queue, 1) == ["3"]


async def test_a_closed_candle_is_never_dropped_silently() -> None:
    queue = ClientQueue(limit=2)
    queue.put(CANDLE, FORMING)
    queue.put(CANDLE, FORMING)
    queue.put(CANDLE, CLOSED)  # The queue is full.
    first = json.loads(await asyncio.wait_for(queue.get(), 1))
    assert first == {"type": "resync", "topic": CANDLE}


async def test_a_forming_update_is_dropped_when_full_with_no_resync() -> None:
    queue = ClientQueue(limit=1)
    queue.put(CANDLE, FORMING)
    queue.put(CANDLE, FORMING)
    assert queue.resync == []


async def test_the_queue_stays_bounded_while_a_client_stalls() -> None:
    queue = ClientQueue(limit=8)
    for _ in range(10_000):
        queue.put(CANDLE, CLOSED)
    assert len(queue._items) == 8
    assert queue.resync == [CANDLE]


async def test_order_is_preserved_for_candle_events() -> None:
    queue = ClientQueue()
    queue.put(CANDLE, "a")
    queue.put(CANDLE, "b")
    assert await drain(queue, 2) == ["a", "b"]


def test_hub_delivers_only_to_subscribers() -> None:
    hub = Hub()
    wants_it, ignores_it = ClientQueue(), ClientQueue()
    hub.add(wants_it)
    hub.add(ignores_it)
    hub.subscribe(wants_it, [PRICE])
    hub.deliver(PRICE, "x")
    assert len(wants_it._items) == 1
    assert len(ignores_it._items) == 0


def test_removed_client_receives_nothing() -> None:
    hub = Hub()
    queue = ClientQueue()
    hub.add(queue)
    hub.subscribe(queue, [PRICE])
    hub.remove(queue)
    hub.deliver(PRICE, "x")
    assert len(queue._items) == 0
