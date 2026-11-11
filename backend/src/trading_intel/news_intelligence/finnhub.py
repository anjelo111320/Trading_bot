"""Finnhub's crypto news (D032): a licensed API, read with the owner's free personal key.

Finnhub's terms, read on 2026-11-11, allow personal use only and forbid sharing the data,
which fits D006: everything stays on this computer for the owner. Items are headlines,
publisher summaries and links. Article pages are never requested. The key travels in a
header, so it never appears in a URL or a log line.
"""

import asyncio
from datetime import UTC, datetime
from typing import Final

import httpx
import structlog

from trading_intel.core.clock import Clock
from trading_intel.news_intelligence.normalize import clean_text
from trading_intel.news_intelligence.official_sources import (
    HEADERS,
    MAX_HEADLINE,
    MAX_SNIPPET,
    FeedError,
    FeedItem,
    NewsArchive,
)

log = structlog.get_logger(__name__)

NEWS_URL: Final = "https://finnhub.io/api/v1/news"
CATEGORY: Final = "crypto"
POLL_SECONDS: Final = 120  # The free plan allows 60 calls a minute; this uses one in 120.
MAX_PUBLISHER: Final = 100


def parse_news(payload: object) -> list[FeedItem]:
    """Finnhub's JSON is untrusted. An item missing an id, title, safe link or time is skipped."""
    if not isinstance(payload, list):
        raise FeedError("not a list")
    items: list[FeedItem] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        ident, stamp = entry.get("id"), entry.get("datetime")
        headline = clean_text(str(entry.get("headline") or ""))
        url = str(entry.get("url") or "").strip()
        if (
            not isinstance(ident, int)
            or isinstance(ident, bool)
            or not isinstance(stamp, int)
            or isinstance(stamp, bool)
            or stamp <= 0
            or not headline
            or not url.startswith("https://")
        ):
            continue
        summary = clean_text(str(entry.get("summary") or ""))
        publisher = clean_text(str(entry.get("source") or ""))[:MAX_PUBLISHER]
        items.append(
            FeedItem(
                headline[:MAX_HEADLINE],
                url,
                summary[:MAX_SNIPPET] or None,
                datetime.fromtimestamp(stamp, UTC),
                external_id=str(ident),
                extra={"publisher": publisher} if publisher else None,
            )
        )
    return items


class FinnhubNewsCollector:
    def __init__(
        self,
        archive: NewsArchive,
        clock: Clock,
        key: str,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._archive = archive
        self._clock = clock
        self._key = key
        self._http = http or httpx.AsyncClient(timeout=20, headers=HEADERS)
        self._newest_id = 0  # Finnhub returns only items above this id once it is set.

    async def poll_once(self) -> int:
        params = {"category": CATEGORY}
        if self._newest_id:
            params["minId"] = str(self._newest_id)
        response = await self._http.get(
            NEWS_URL, params=params, headers={"X-Finnhub-Token": self._key}
        )
        response.raise_for_status()
        items = parse_news(response.json())
        stored = await self._archive.store(items, self._clock.now())
        self._newest_id = max([self._newest_id, *(int(item.external_id or 0) for item in items)])
        return stored

    async def run(self) -> None:
        """Poll forever. A refused key or an outage is logged and waits for the next poll."""
        while True:
            try:
                stored = await self.poll_once()
                if stored:
                    log.info("finnhub_news_stored", stored=stored)
            except httpx.HTTPStatusError as error:
                log.warning("finnhub_news_failed", status=error.response.status_code)
            except Exception as error:
                log.warning("finnhub_news_failed", error=type(error).__name__)
            await asyncio.sleep(POLL_SECONDS)
