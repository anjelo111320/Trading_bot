"""The Binance provider. One class serves spot and USD-M, described by a Venue."""

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import structlog

from trading_intel.core.clock import Clock, to_epoch_ms
from trading_intel.core.errors import ProviderError
from trading_intel.data_providers.base import (
    CandleSubscription,
    LinkDown,
    LinkUp,
    MarketEvent,
    MarketEventRejected,
    ProviderCapabilities,
)
from trading_intel.data_providers.binance import parse
from trading_intel.data_providers.binance.parse import CandleContext, MalformedFrame
from trading_intel.data_providers.binance.rest import BinanceRestClient
from trading_intel.data_providers.binance.stream import (
    BadFrame,
    Connected,
    Connector,
    Disconnected,
    Frame,
    ResilientStream,
    StreamItem,
    connect_websocket,
)
from trading_intel.domain.base import DataOrigin
from trading_intel.domain.candles import ClosedCandle, Timeframe
from trading_intel.domain.instruments import Instrument, InstrumentRules
from trading_intel.domain.market import FundingRate, OpenInterest

log = structlog.get_logger(__name__)

PAGE_SIZE = 1000
FUNDING_PAGE_SIZE = 1000
EXCHANGE_INFO_WEIGHT = 20


@dataclass(frozen=True)
class Venue:
    code: str
    capabilities: ProviderCapabilities
    time_path: str
    klines_path: str
    exchange_info_path: str
    exchange_info_by_symbol: bool
    klines_weight: int
    rest_cap_per_minute: int
    # Route name to URL path. A path may hold one combined connection.
    routes: Mapping[str, str]
    route_of_stream: Callable[[str], str]
    extra_paths: frozenset[str] = field(default_factory=frozenset)

    @property
    def allowed_paths(self) -> frozenset[str]:
        base = {self.time_path, self.klines_path, self.exchange_info_path}
        return frozenset(base) | self.extra_paths


SPOT = Venue(
    code="binance_spot",
    capabilities=ProviderCapabilities(bid_ask=True),
    time_path="/api/v3/time",
    klines_path="/api/v3/klines",
    exchange_info_path="/api/v3/exchangeInfo",
    exchange_info_by_symbol=True,
    klines_weight=2,
    rest_cap_per_minute=1500,
    routes={"spot": "/stream"},
    route_of_stream=lambda _stream: "spot",
)


def _usdm_route(stream: str) -> str:
    """Binance splits futures streams by route. The legacy path silently drops klines."""
    return "public" if "bookTicker" in stream or "depth" in stream else "market"


USDM = Venue(
    code="binance_usdm",
    capabilities=ProviderCapabilities(
        bid_ask=True, funding=True, open_interest=True, liquidations=True
    ),
    time_path="/fapi/v1/time",
    klines_path="/fapi/v1/klines",
    exchange_info_path="/fapi/v1/exchangeInfo",
    exchange_info_by_symbol=False,
    klines_weight=5,
    rest_cap_per_minute=600,
    routes={"market": "/market/stream", "public": "/public/stream"},
    route_of_stream=_usdm_route,
    extra_paths=frozenset(
        {
            "/fapi/v1/fundingRate",
            "/fapi/v1/openInterest",
            "/fapi/v1/premiumIndex",
            "/futures/data/openInterestHist",
        }
    ),
)


class BinanceProvider:
    def __init__(
        self,
        venue: Venue,
        provider_id: int,
        symbols: Mapping[int, str],
        rest: BinanceRestClient,
        ws_url: str,
        clock: Clock,
        *,
        connector: Connector = connect_websocket,
    ) -> None:
        self._venue = venue
        self._provider_id = provider_id
        self._symbols = symbols
        self._instrument_of = {symbol: key for key, symbol in symbols.items()}
        self._rest = rest
        self._ws_url = ws_url
        self._clock = clock
        self._connector = connector

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._venue.capabilities

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        await self._rest.close()

    async def get_server_time(self) -> datetime:
        body = await self._rest.get(self._venue.time_path, {}, 1)
        return parse.timestamp(body["serverTime"])

    async def get_instrument_rules(self, instrument: Instrument) -> InstrumentRules:
        symbol = self._symbols[instrument.id]
        params = {"symbol": symbol} if self._venue.exchange_info_by_symbol else {}
        body = await self._rest.get(self._venue.exchange_info_path, params, EXCHANGE_INFO_WEIGHT)
        for info in body["symbols"]:
            if info["symbol"] == symbol:
                return parse.parse_rules(info, instrument.instrument_type)
        raise ProviderError(f"{symbol} is missing from exchange information")

    async def get_historical_candles(
        self,
        instrument: Instrument,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
        origin: DataOrigin = DataOrigin.BACKFILL,
    ) -> AsyncIterator[ClosedCandle]:
        """Yield closed candles with an open time in [start, end), in order."""
        symbol = self._symbols[instrument.id]
        cursor = start
        while cursor < end:
            params = {
                "symbol": symbol,
                "interval": timeframe.value,
                "startTime": to_epoch_ms(cursor),
                "endTime": to_epoch_ms(end) - 1,
                "limit": PAGE_SIZE,
            }
            rows = await self._rest.get(self._venue.klines_path, params, self._venue.klines_weight)
            if not rows:
                return
            server_time = await self.get_server_time()
            context = CandleContext(
                self._provider_id, instrument.id, timeframe, origin, self._clock.now()
            )
            last_open = cursor
            for row in rows:
                candle = parse.parse_rest_kline(row, context, server_time)
                if candle is None:
                    return
                last_open = candle.open_time
                yield candle
            cursor = timeframe.next_open(last_open)
            if len(rows) < PAGE_SIZE:
                return

    def stream_market(
        self,
        subscriptions: Sequence[CandleSubscription],
        book_instruments: Sequence[Instrument],
        *,
        mark_instruments: Sequence[Instrument] = (),
        liquidation_instruments: Sequence[Instrument] = (),
    ) -> AsyncIterator[MarketEvent]:
        names = [
            f"{self._symbols[s.instrument.id].lower()}@kline_{s.timeframe.value}"
            for s in subscriptions
        ]
        names += [f"{self._symbols[i.id].lower()}@bookTicker" for i in book_instruments]
        names += [f"{self._symbols[i.id].lower()}@markPrice@1s" for i in mark_instruments]
        names += [f"{self._symbols[i.id].lower()}@forceOrder" for i in liquidation_instruments]
        return self._merged(self._route_streams(names))

    def _route_streams(self, names: Sequence[str]) -> dict[str, ResilientStream]:
        by_route: dict[str, list[str]] = {}
        for name in names:
            by_route.setdefault(self._venue.route_of_stream(name), []).append(name)
        return {
            route: ResilientStream(
                route,
                f"{self._ws_url}{self._venue.routes[route]}?streams={'/'.join(streams)}",
                self._clock,
                connector=self._connector,
            )
            for route, streams in by_route.items()
        }

    async def _merged(self, streams: dict[str, ResilientStream]) -> AsyncIterator[MarketEvent]:
        queue: asyncio.Queue[StreamItem] = asyncio.Queue(maxsize=10_000)

        async def forward(stream: ResilientStream) -> None:
            async for item in stream.items():
                await queue.put(item)

        tasks = [asyncio.create_task(forward(stream)) for stream in streams.values()]
        try:
            while True:
                for task in tasks:
                    if task.done():
                        task.result()
                item = await queue.get()
                event = self._translate(item)
                if event is not None:
                    yield event
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    def _translate(self, item: StreamItem) -> MarketEvent | None:
        now = self._clock.now()
        match item:
            case Connected(route):
                return LinkUp(route=route, at=now)
            case Disconnected(route, reason):
                return LinkDown(route=route, reason=reason, at=now)
            case BadFrame(route, reason):
                return MarketEventRejected(route=route, reason=reason, at=now)
            case Frame(route, payload):
                try:
                    return self._parse_frame(payload, now)
                except MalformedFrame as error:
                    return MarketEventRejected(route=route, reason=error.reason, at=now)
        return None

    def _parse_frame(self, payload: Mapping[str, Any], now: datetime) -> MarketEvent | None:
        stream = payload.get("stream")
        data = payload.get("data")
        if not isinstance(stream, str) or not isinstance(data, dict):
            return None  # Control replies have neither field.
        symbol, _, kind = stream.partition("@")
        instrument_id = self._instrument_of.get(symbol.upper())
        if instrument_id is None:
            raise MalformedFrame("unknown_symbol")
        if kind.startswith("kline_"):
            timeframe = Timeframe(kind.removeprefix("kline_"))
            context = CandleContext(
                self._provider_id, instrument_id, timeframe, DataOrigin.LIVE, now
            )
            return parse.parse_stream_kline(data, context)
        if kind == "bookTicker":
            return parse.parse_book_ticker(data, self._provider_id, instrument_id, now)
        if kind.startswith("markPrice"):
            return parse.parse_mark_price(data, self._provider_id, instrument_id, now)
        if kind == "forceOrder":
            return parse.parse_force_order(data, self._provider_id, instrument_id, now)
        raise MalformedFrame("unknown_stream")

    async def get_funding_history(
        self, instrument: Instrument, start: datetime
    ) -> AsyncIterator[FundingRate]:
        symbol = self._symbols[instrument.id]
        cursor = to_epoch_ms(start)
        while True:
            params = {"symbol": symbol, "startTime": cursor, "limit": FUNDING_PAGE_SIZE}
            rows = await self._rest.get("/fapi/v1/fundingRate", params, 1)
            if not rows:
                return
            for row in rows:
                yield parse.parse_funding(row, self._provider_id, instrument.id, self._clock.now())
            cursor = rows[-1]["fundingTime"] + 1
            if len(rows) < FUNDING_PAGE_SIZE:
                return

    async def get_open_interest(self, instrument: Instrument) -> OpenInterest:
        body = await self._rest.get(
            "/fapi/v1/openInterest", {"symbol": self._symbols[instrument.id]}, 1
        )
        return parse.parse_open_interest(body, self._provider_id, instrument.id, self._clock.now())

    async def get_open_interest_history(
        self, instrument: Instrument, start: datetime
    ) -> AsyncIterator[OpenInterest]:
        """Binance keeps about one month, at 5-minute resolution."""
        cursor = start
        end = self._clock.now()
        while cursor < end:
            params = {
                "symbol": self._symbols[instrument.id],
                "period": "5m",
                "startTime": to_epoch_ms(cursor),
                "limit": 500,
            }
            rows = await self._rest.get("/futures/data/openInterestHist", params, 0)
            if not rows:
                return
            for row in rows:
                yield parse.parse_open_interest_history(
                    row, self._provider_id, instrument.id, self._clock.now()
                )
            cursor = parse.timestamp(rows[-1]["timestamp"]) + timedelta(minutes=5)
            if len(rows) < 500:
                return
