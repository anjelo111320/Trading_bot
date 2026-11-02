import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from websockets.asyncio.server import ServerConnection

from tests.failure.fake_exchange import collect, running, send_json, stay_open
from trading_intel.core.clock import SystemClock
from trading_intel.data_providers.base import (
    CandleSubscription,
    LinkDown,
    LinkUp,
    MarketEventRejected,
)
from trading_intel.data_providers.binance.provider import SPOT, USDM, BinanceProvider, Venue
from trading_intel.data_providers.binance.rest import BinanceRestClient
from trading_intel.data_providers.binance.stream import (
    BadFrame,
    Connected,
    Disconnected,
    Frame,
    ResilientStream,
)
from trading_intel.domain.candles import ClosedCandle, FormingCandle, Timeframe
from trading_intel.domain.instruments import Instrument, InstrumentType
from trading_intel.domain.market import MarkPrice, TopOfBook

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SPOT_FRAMES: list[dict[str, Any]] = json.loads(
    (FIXTURES / "binance_spot/stream_frames.json").read_text()
)
BTC = Instrument(
    id=1,
    symbol="BTCUSDT",
    instrument_type=InstrumentType.SPOT,
    base_asset="BTC",
    quote_asset="USDT",
    settle_asset="USDT",
)


def stream(url: str, **options: Any) -> ResilientStream:
    return ResilientStream("test", url, SystemClock(), min_spacing=0.01, **options)


async def test_frames_arrive_after_a_connected_notice() -> None:
    async def behaviour(connection: ServerConnection, _: int) -> None:
        await send_json(connection, {"n": 1})
        await stay_open(connection)

    async with running(behaviour) as exchange:
        items = await collect(stream(exchange.url).items(), 2)
    assert items == [Connected("test"), Frame("test", {"n": 1})]


async def test_a_dropped_connection_reconnects_by_itself() -> None:
    async def behaviour(connection: ServerConnection, number: int) -> None:
        await send_json(connection, {"connection": number})
        if number == 1:
            await connection.close()
        else:
            await stay_open(connection)

    async with running(behaviour) as exchange:
        items = await collect(stream(exchange.url).items(), 5)
    assert Frame("test", {"connection": 1}) in items
    assert Frame("test", {"connection": 2}) in items
    assert any(isinstance(item, Disconnected) for item in items)
    assert exchange.connections == 2


async def test_server_shutdown_notice_triggers_a_reconnect() -> None:
    async def behaviour(connection: ServerConnection, number: int) -> None:
        if number == 1:
            await send_json(connection, {"e": "serverShutdown", "E": 1})
        else:
            await send_json(connection, {"ok": True})
        await stay_open(connection)

    async with running(behaviour) as exchange:
        items = await collect(stream(exchange.url).items(), 4)
    assert Disconnected("test", "server shutdown notice") in items
    assert Frame("test", {"ok": True}) in items


async def test_malformed_frames_are_reported_without_killing_the_stream() -> None:
    async def behaviour(connection: ServerConnection, _: int) -> None:
        await connection.send("{not json")
        await connection.send("[1, 2]")
        await send_json(connection, {"ok": True})
        await stay_open(connection)

    async with running(behaviour) as exchange:
        items = await collect(stream(exchange.url).items(), 4)
    assert items[1:] == [
        BadFrame("test", "invalid_json"),
        BadFrame("test", "frame_not_an_object"),
        Frame("test", {"ok": True}),
    ]
    assert exchange.connections == 1


async def test_rollover_opens_the_new_connection_before_closing_the_old() -> None:
    async def behaviour(connection: ServerConnection, number: int) -> None:
        for sequence in range(1000):
            await send_json(connection, {"connection": number, "sequence": sequence})
            await asyncio.sleep(0.01)

    async with running(behaviour) as exchange:
        link = stream(exchange.url, rollover_after=0.15, overlap=0.1).items()
        items = await collect(link, 60)
        await link.aclose()
    frames = [item.payload for item in items if isinstance(item, Frame)]
    assert exchange.connections >= 2
    assert exchange.max_open == 2
    assert not any(isinstance(item, Disconnected) for item in items)
    assert {frame["connection"] for frame in frames} >= {1, 2}


async def test_automatic_pong_keeps_the_link_alive_past_the_server_timeout() -> None:
    async def behaviour(connection: ServerConnection, _: int) -> None:
        await asyncio.sleep(0.5)
        await send_json(connection, {"still": "open"})
        await stay_open(connection)

    async with running(behaviour, ping_interval=0.05, ping_timeout=0.1) as exchange:
        items = await collect(stream(exchange.url).items(), 2)
    assert items[1] == Frame("test", {"still": "open"})
    assert exchange.connections == 1


async def test_connection_failures_report_and_keep_trying() -> None:
    unused_port = "ws://127.0.0.1:9"
    items = await collect(stream(unused_port).items(), 2, limit=10)
    assert all(isinstance(item, Disconnected) for item in items)


def binance(venue: Venue, url: str, symbols: dict[int, str] | None = None) -> BinanceProvider:
    clock = SystemClock()
    rest = BinanceRestClient("https://binance.test", venue.allowed_paths, 100, clock)
    return BinanceProvider(venue, 1, symbols or {1: "BTCUSDT"}, rest, url, clock)


async def test_recorded_spot_frames_become_domain_events() -> None:
    async def behaviour(connection: ServerConnection, _: int) -> None:
        for frame in SPOT_FRAMES:
            await send_json(connection, frame)
        await stay_open(connection)

    subscription = CandleSubscription(instrument=BTC, timeframe=Timeframe.M1)
    async with running(behaviour) as exchange:
        provider = binance(SPOT, exchange.url)
        events = await collect(provider.stream_market([subscription], [BTC]), len(SPOT_FRAMES) + 1)
    assert isinstance(events[0], LinkUp)
    assert exchange.paths[0].startswith("/stream?streams=btcusdt@kline_1m/btcusdt@bookTicker")
    kinds = {type(event) for event in events[1:]}
    assert kinds == {TopOfBook, FormingCandle, ClosedCandle}


async def test_usdm_uses_two_routes_and_never_the_legacy_path() -> None:
    async def behaviour(connection: ServerConnection, _: int) -> None:
        await stay_open(connection)

    subscription = CandleSubscription(instrument=BTC, timeframe=Timeframe.M1)
    async with running(behaviour) as exchange:
        provider = binance(USDM, exchange.url)
        link = provider.stream_market([subscription], [BTC], mark_instruments=[BTC])
        events = await collect(link, 2)
        await link.aclose()
    assert all(isinstance(event, LinkUp) for event in events)
    paths = sorted(exchange.paths)
    assert paths[0].startswith("/market/stream?streams=btcusdt@kline_1m/btcusdt@markPrice@1s")
    assert paths[1].startswith("/public/stream?streams=btcusdt@bookTicker")
    assert not any(path.startswith(("/stream", "/ws")) for path in paths)


async def test_usdm_frames_route_to_the_right_types() -> None:
    market = json.loads((FIXTURES / "binance_usdm/market_stream_frames.json").read_text())

    async def behaviour(connection: ServerConnection, _: int) -> None:
        for frame in market:
            await send_json(connection, frame)
        await stay_open(connection)

    subscription = CandleSubscription(instrument=BTC, timeframe=Timeframe.M1)
    async with running(behaviour) as exchange:
        provider = binance(USDM, exchange.url)
        link = provider.stream_market([subscription], [], mark_instruments=[BTC])
        events = await collect(link, len(market) + 1)
        await link.aclose()
    assert MarkPrice in {type(event) for event in events}


async def test_a_bad_frame_becomes_a_rejection_event() -> None:
    async def behaviour(connection: ServerConnection, _: int) -> None:
        await send_json(connection, {"stream": "btcusdt@kline_1m", "data": {"k": {"t": 1}}})
        await send_json(connection, {"stream": "dogeusdt@bookTicker", "data": {}})
        await stay_open(connection)

    subscription = CandleSubscription(instrument=BTC, timeframe=Timeframe.M1)
    async with running(behaviour) as exchange:
        provider = binance(SPOT, exchange.url)
        link = provider.stream_market([subscription], [])
        events = await collect(link, 3)
        await link.aclose()
    assert [type(event) for event in events[1:]] == [MarketEventRejected, MarketEventRejected]


async def test_link_down_is_reported_to_consumers() -> None:
    async def behaviour(connection: ServerConnection, number: int) -> None:
        if number == 1:
            await connection.close()
        else:
            await stay_open(connection)

    subscription = CandleSubscription(instrument=BTC, timeframe=Timeframe.M1)
    async with running(behaviour) as exchange:
        provider = binance(SPOT, exchange.url)
        link = provider.stream_market([subscription], [])
        events = await collect(link, 3)
        await link.aclose()
    assert any(isinstance(event, LinkDown) for event in events)


def test_stream_timestamps_use_utc() -> None:
    assert SystemClock().now().tzinfo is UTC
    assert datetime.now(UTC).tzinfo is UTC


@pytest.mark.parametrize("venue", [SPOT, USDM])
def test_declared_routes_exist(venue: Venue) -> None:
    for name in ("btcusdt@kline_1m", "btcusdt@bookTicker"):
        assert venue.route_of_stream(name) in venue.routes
