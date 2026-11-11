"""Finnhub's crypto news and Binance's announcement stream (D032). All payloads are made up."""

import asyncio
import hashlib
import hmac
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest
import respx
import websockets
from websockets.frames import Close

from trading_intel.core.clock import FixedClock
from trading_intel.news_intelligence import binance_announcements, finnhub
from trading_intel.news_intelligence.binance_announcements import (
    REST_URL,
    RESTRICTIONS_PATH,
    STREAM_URL,
    TOPIC,
    BinanceAnnouncementCollector,
    KeyNotReadOnlyError,
    parse_message,
    refused_permissions,
    signed_query,
)
from trading_intel.news_intelligence.finnhub import NEWS_URL, FinnhubNewsCollector, parse_news
from trading_intel.news_intelligence.official_sources import FeedError, FeedItem

NOW = datetime(2026, 11, 11, 8, tzinfo=UTC)
KEY = "test-key-not-real"
SECRET = "test-secret-not-real"


class MemoryArchive:
    def __init__(self) -> None:
        self.items: list[FeedItem] = []

    async def store(self, items: list[FeedItem], now: datetime) -> int:
        new = [item for item in items if item.url not in {kept.url for kept in self.items}]
        self.items += new
        return len(new)


def finnhub_item(ident: int, **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "category": "crypto",
        "datetime": 1_762_848_000,
        "headline": "Zcash rallies as shielded supply grows",
        "id": ident,
        "image": "https://example.test/i.png",
        "related": "",
        "source": "Example Wire",
        "summary": "<p>Short summary.</p>",
        "url": f"https://example.test/news/{ident}",
    }
    return {**values, **overrides}


def test_finnhub_items_keep_their_id_time_and_publisher() -> None:
    [item] = parse_news([finnhub_item(7151)])
    assert item.headline == "Zcash rallies as shielded supply grows"
    assert item.snippet == "Short summary."  # Markup removed.
    assert item.published_at == datetime(2025, 11, 11, 8, tzinfo=UTC)
    assert item.external_id == "7151"
    assert item.extra == {"publisher": "Example Wire"}


@pytest.mark.parametrize(
    "broken",
    [
        {"url": "javascript:alert(1)"},
        {"url": "http://example.test/plain"},
        {"headline": "  "},
        {"datetime": None},
        {"datetime": True},
        {"datetime": 0},
        {"id": "7151"},
    ],
)
def test_finnhub_items_without_a_safe_link_title_time_or_id_are_skipped(
    broken: dict[str, object],
) -> None:
    assert parse_news([finnhub_item(1, **broken), "not an item"]) == []


def test_a_finnhub_reply_that_is_not_a_list_is_refused() -> None:
    with pytest.raises(FeedError):
        parse_news({"error": "You don't have access to this resource."})


@respx.mock
async def test_finnhub_sends_the_key_as_a_header_and_asks_only_for_newer_items() -> None:
    route = respx.get(NEWS_URL).mock(
        side_effect=[
            httpx.Response(200, json=[finnhub_item(7151), finnhub_item(7150)]),
            httpx.Response(200, json=[finnhub_item(7152)]),
        ]
    )
    archive = MemoryArchive()
    collector = FinnhubNewsCollector(archive, FixedClock(NOW), KEY)  # type: ignore[arg-type]
    assert await collector.poll_once() == 2
    assert await collector.poll_once() == 1
    first, second = (call.request for call in route.calls)
    assert first.headers["X-Finnhub-Token"] == KEY
    assert KEY not in str(first.url)  # Never in a URL, which could be logged.
    assert dict(first.url.params) == {"category": "crypto"}
    assert dict(second.url.params) == {"category": "crypto", "minId": "7151"}


@respx.mock
async def test_a_refused_finnhub_key_is_logged_and_polled_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    respx.get(NEWS_URL).mock(return_value=httpx.Response(403, json={"error": "no access"}))
    collector = FinnhubNewsCollector(MemoryArchive(), FixedClock(NOW), KEY)  # type: ignore[arg-type]
    polls = 0

    async def sleep(seconds: float) -> None:
        nonlocal polls
        polls += 1
        if polls == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(finnhub.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await collector.run()
    assert polls == 2  # It kept going rather than ending the ingestor's task.


def test_binance_signs_every_parameter_sorted_by_name() -> None:
    query = signed_query(
        {"topic": TOPIC, "timestamp": "1", "random": "ab", "recvWindow": "5"}, SECRET
    )
    payload, signature = query.rsplit("&signature=", 1)
    assert payload == f"random=ab&recvWindow=5&timestamp=1&topic={TOPIC}"
    expected = hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    assert signature == expected


@pytest.mark.parametrize(
    "permission",
    [
        "enableSpotAndMarginTrading",
        "enableFutures",
        "enableWithdrawals",
        "enableInternalTransfer",
        "permitsUniversalTransfer",
        "enableSomethingBinanceAddsLater",
    ],
)
def test_a_key_that_can_do_more_than_read_is_refused(permission: str) -> None:
    restrictions = {"ipRestrict": True, "enableReading": True, permission: True}
    assert refused_permissions(restrictions) == [permission]


def test_a_read_only_key_is_accepted() -> None:
    restrictions = {
        "ipRestrict": True,
        "createTime": 1_762_848_000_000,
        "enableReading": True,
        "enableFixReadOnly": True,
        "enableSpotAndMarginTrading": False,
        "enableWithdrawals": False,
        "enableFutures": False,
    }
    assert refused_permissions(restrictions) == []


def announcement(**overrides: object) -> str:
    data: dict[str, object] = {
        "catalogId": 48,
        "catalogName": "New Cryptocurrency Listing",
        "publishDate": 1_762_848_000_000,
        "title": "Binance Futures Will Launch USDⓈ-Margined ZECUSDT Perpetual Contract",
        "body": "<p>Fellow Binancians, ...</p>",
        "disclaimer": "Disclaimer text",
    }
    data.update(overrides)
    return json.dumps({"type": "DATA", "topic": TOPIC, "data": json.dumps(data)})


def test_an_announcement_becomes_one_item_with_its_catalogue_and_time() -> None:
    item = parse_message(announcement())
    assert item is not None
    assert item.headline.startswith("Binance Futures Will Launch")
    assert item.snippet == "Fellow Binancians, ..."
    assert item.published_at == datetime(2025, 11, 11, 8, tzinfo=UTC)
    assert item.external_id == "48:1762848000000"
    assert item.extra == {"catalog_id": 48, "catalog": "New Cryptocurrency Listing"}
    assert item.url.startswith("https://www.binance.com/en/support/announcement/list/48#")


def test_two_announcements_at_one_moment_keep_separate_addresses() -> None:
    first = parse_message(announcement(title="First notice"))
    second = parse_message(announcement(title="Second notice"))
    assert first is not None and second is not None
    assert first.url != second.url


@pytest.mark.parametrize(
    "raw",
    [
        json.dumps({"type": "COMMAND", "data": "SUCCESS", "subType": "SUBSCRIBE"}),
        json.dumps({"type": "DATA", "topic": "other_topic", "data": "{}"}),
        announcement(title=""),
        announcement(publishDate="soon"),
        announcement(catalogId=None),
        json.dumps({"type": "DATA", "topic": TOPIC, "data": "not json"}),
        "not json at all",
    ],
)
def test_anything_but_a_complete_announcement_is_ignored(raw: str) -> None:
    assert parse_message(raw) is None


class FakeConnection:
    def __init__(self, messages: list[str]) -> None:
        self.messages = messages
        self.closed = False

    async def recv(self) -> str:
        if not self.messages:
            raise websockets.ConnectionClosedOK(Close(1000, "24 hours"), None)
        return self.messages.pop(0)

    async def close(self) -> None:
        self.closed = True


def read_only(**extra: bool) -> httpx.Response:
    return httpx.Response(200, json={"ipRestrict": True, "enableReading": True, **extra})


@respx.mock
async def test_the_stream_is_signed_and_stores_each_announcement() -> None:
    respx.get(url__startswith=f"{REST_URL}{RESTRICTIONS_PATH}").mock(return_value=read_only())
    connection = FakeConnection(
        [json.dumps({"type": "COMMAND", "data": "SUCCESS"}), announcement()]
    )
    opened: list[tuple[str, Mapping[str, str]]] = []

    async def connect(url: str, headers: Mapping[str, str]) -> FakeConnection:
        opened.append((url, headers))
        return connection

    archive = MemoryArchive()
    collector = BinanceAnnouncementCollector(
        archive,
        FixedClock(NOW),
        KEY,
        SECRET,
        connect=connect,  # type: ignore[arg-type]
    )
    await collector.check_key()
    assert await collector.listen_once() == 1
    [(url, headers)] = opened
    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == STREAM_URL
    params = dict(parse_qsl(parts.query))
    assert params["topic"] == TOPIC
    assert params["timestamp"] == str(int(NOW.timestamp() * 1000))
    assert SECRET not in url
    assert headers == {"X-MBX-APIKEY": KEY}
    assert connection.closed
    assert len(archive.items) == 1


@respx.mock
async def test_a_key_that_can_trade_never_opens_the_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    respx.get(url__startswith=f"{REST_URL}{RESTRICTIONS_PATH}").mock(
        return_value=read_only(enableFutures=True)
    )
    opened = 0

    async def connect(url: str, headers: Mapping[str, str]) -> FakeConnection:
        nonlocal opened
        opened += 1
        return FakeConnection([])

    collector = BinanceAnnouncementCollector(
        MemoryArchive(),
        FixedClock(NOW),
        KEY,
        SECRET,
        connect=connect,  # type: ignore[arg-type]
    )
    with pytest.raises(KeyNotReadOnlyError, match="enableFutures"):
        await collector.check_key()

    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        if len(waits) == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(binance_announcements.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await collector.run()
    assert opened == 0
    assert waits == [3600.0, 3600.0]  # Checked again hourly; the ingestor's task never ends.


@respx.mock
async def test_a_stream_that_keeps_closing_backs_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Binance may block an IP that reconnects too often."""
    respx.get(url__startswith=f"{REST_URL}{RESTRICTIONS_PATH}").mock(return_value=read_only())

    async def connect(url: str, headers: Mapping[str, str]) -> FakeConnection:
        return FakeConnection([])

    collector = BinanceAnnouncementCollector(
        MemoryArchive(),
        FixedClock(NOW),
        KEY,
        SECRET,
        connect=connect,  # type: ignore[arg-type]
    )
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        if len(waits) == 4:
            raise asyncio.CancelledError

    monkeypatch.setattr(binance_announcements.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await collector.run()
    assert waits == [2.0, 4.0, 8.0, 16.0]


@respx.mock
async def test_article_pages_are_never_requested() -> None:
    respx.get(NEWS_URL).mock(return_value=httpx.Response(200, json=[finnhub_item(1)]))
    await FinnhubNewsCollector(MemoryArchive(), FixedClock(NOW), KEY).poll_once()  # type: ignore[arg-type]
    assert {call.request.url.host for call in respx.calls} == {"finnhub.io"}
