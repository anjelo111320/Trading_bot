"""Binance's official announcements, pushed over its CMS WebSocket (D032).

Listings, delistings and contract changes for the coins traded here, the moment Binance
publishes them. The stream needs an API key from the owner's main Binance account, so the key
must be read-only. Before any connection, Binance is asked what the key may do, and a key that
can trade, withdraw or transfer is refused. This module calls no other endpoint, and article
pages are never requested.

Announcements published while the stream is down are not sent again, so they are missed.
"""

import asyncio
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Final, Protocol
from urllib.parse import urlencode

import httpx
import structlog
import websockets

from trading_intel.core.clock import Clock
from trading_intel.news_intelligence.normalize import clean_text
from trading_intel.news_intelligence.official_sources import (
    HEADERS,
    MAX_HEADLINE,
    MAX_SNIPPET,
    FeedItem,
    NewsArchive,
)

log = structlog.get_logger(__name__)

# Fixed in code, so no setting can point the key anywhere else.
REST_URL: Final = "https://api.binance.com"
STREAM_URL: Final = "wss://api.binance.com/sapi/wss"
RESTRICTIONS_PATH: Final = "/sapi/v1/account/apiRestrictions"
TOPIC: Final = "com_announcement_en"
RECV_WINDOW: Final = 30_000
PING_SECONDS: Final = 30  # Binance closes a connection that sends no ping for a minute.
MAX_BACKOFF: Final = 60.0
STEADY_SECONDS: Final = 60.0
RECHECK_SECONDS: Final = 3600.0
LIST_URL: Final = "https://www.binance.com/en/support/announcement/list/{catalog}"
# Permissions a key may hold and still be used. Any other permission that is on, including
# ones Binance adds later, refuses the key.
READ_ONLY: Final = frozenset({"enableReading", "enableFixReadOnly", "ipRestrict"})


class KeyNotReadOnlyError(RuntimeError):
    """The key can do more than read, so it is never used."""


class Connection(Protocol):
    async def recv(self) -> str | bytes: ...

    async def close(self) -> None: ...


Connector = Callable[[str, Mapping[str, str]], Awaitable[Connection]]


async def connect_websocket(url: str, headers: Mapping[str, str]) -> Connection:
    return await websockets.connect(
        url,
        additional_headers=dict(headers),
        open_timeout=10,
        ping_interval=PING_SECONDS,
        ping_timeout=20,
    )


def signed_query(params: Mapping[str, str], secret: str) -> str:
    """Binance signs every parameter but the signature, sorted by name, with HMAC SHA256."""
    query = urlencode(sorted(params.items()))
    signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    return f"{query}&signature={signature}"


def refused_permissions(restrictions: Mapping[str, object]) -> list[str]:
    return sorted(
        name for name, value in restrictions.items() if value is True and name not in READ_ONLY
    )


def parse_message(raw: str | bytes) -> FeedItem | None:
    """One pushed announcement, or None for anything else. The payload is untrusted."""
    try:
        message = json.loads(raw)
        if not isinstance(message, dict) or message.get("type") != "DATA":
            return None
        if message.get("topic") != TOPIC:
            return None
        data = message.get("data")
        payload = json.loads(data) if isinstance(data, str) else data
    except json.JSONDecodeError, TypeError:
        return None
    if not isinstance(payload, dict):
        return None
    title = clean_text(str(payload.get("title") or ""))
    published, catalog = payload.get("publishDate"), payload.get("catalogId")
    if (
        not title
        or not isinstance(published, int)
        or isinstance(published, bool)
        or published <= 0
        or not isinstance(catalog, int)
        or isinstance(catalog, bool)
    ):
        return None
    body = clean_text(str(payload.get("body") or ""))
    catalog_name = clean_text(str(payload.get("catalogName") or ""))[:100]
    # The payload has no link, so this points to its catalogue's list, where it appears. The
    # fragment keeps each announcement's address unique.
    digest = hashlib.sha256(title.encode()).hexdigest()[:8]
    return FeedItem(
        title[:MAX_HEADLINE],
        f"{LIST_URL.format(catalog=catalog)}#{published}-{digest}",
        body[:MAX_SNIPPET] or None,
        datetime.fromtimestamp(published / 1000, UTC),
        external_id=f"{catalog}:{published}",
        extra={"catalog_id": catalog, "catalog": catalog_name},
    )


class BinanceAnnouncementCollector:
    def __init__(
        self,
        archive: NewsArchive,
        clock: Clock,
        key: str,
        secret: str,
        http: httpx.AsyncClient | None = None,
        connect: Connector = connect_websocket,
    ) -> None:
        self._archive = archive
        self._clock = clock
        self._key = key
        self._secret = secret
        self._http = http or httpx.AsyncClient(timeout=20, headers=HEADERS)
        self._connect = connect

    def _signed(self, params: Mapping[str, str]) -> str:
        now = int(self._clock.now().timestamp() * 1000)
        values = {**params, "recvWindow": str(RECV_WINDOW), "timestamp": str(now)}
        return signed_query(values, self._secret)

    async def check_key(self) -> None:
        """Refuse a key that can do more than read. Raises KeyNotReadOnlyError."""
        response = await self._http.get(
            f"{REST_URL}{RESTRICTIONS_PATH}?{self._signed({})}",
            headers={"X-MBX-APIKEY": self._key},
        )
        response.raise_for_status()
        restrictions = response.json()
        if not isinstance(restrictions, dict):
            raise KeyNotReadOnlyError("unreadable permissions")
        refused = refused_permissions(restrictions)
        if refused:
            raise KeyNotReadOnlyError(", ".join(refused))

    async def listen_once(self) -> int:
        """One connection, until Binance closes it (at most 24 hours). Returns items stored."""
        query = self._signed({"random": secrets.token_hex(16), "topic": TOPIC})
        connection = await self._connect(f"{STREAM_URL}?{query}", {"X-MBX-APIKEY": self._key})
        stored = 0
        try:
            while True:
                item = parse_message(await connection.recv())
                if item is None:
                    continue
                added = await self._archive.store([item], self._clock.now())
                stored += added
                if added:
                    log.info(
                        "binance_announcement_stored", catalog=(item.extra or {}).get("catalog")
                    )
        except websockets.ConnectionClosed:
            return stored
        finally:
            await connection.close()

    async def run(self) -> None:
        """Never returns, because the ingestor stops when any of its tasks ends.

        The key is checked before every connection. A refused key is checked again hourly,
        since its permissions can change on Binance without changing the key. A connection that
        ends within a minute backs off like a failure, because Binance may block an IP that
        reconnects too often.
        """
        delay = 1.0
        while True:
            started = time.monotonic()
            try:
                await self.check_key()
                await self.listen_once()
                quick = time.monotonic() - started < STEADY_SECONDS
                delay = min(delay * 2, MAX_BACKOFF) if quick else 1.0
            except KeyNotReadOnlyError as error:
                log.error("binance_announcements_refused", permissions=str(error))
                delay = RECHECK_SECONDS
            except httpx.HTTPStatusError as error:
                log.error("binance_announcements_refused", status=error.response.status_code)
                delay = RECHECK_SECONDS
            except Exception as error:
                log.warning("binance_announcements_disconnected", error=type(error).__name__)
                delay = min(delay * 2, MAX_BACKOFF)
            await asyncio.sleep(delay)
