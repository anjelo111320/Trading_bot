"""A minimal archive of official feeds: no AI, no classification, and no article fetches.

Article URLs are stored but never requested, which avoids scraping and request forgery.
Feed XML is untrusted, so defusedxml refuses entity expansion attacks.
"""

import asyncio
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Final
from xml.etree.ElementTree import ParseError

import defusedxml.ElementTree as SafeXml
import httpx
import structlog
from defusedxml.common import DefusedXmlException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from trading_intel.core.clock import Clock, ensure_utc
from trading_intel.news_intelligence.normalize import clean_text

log = structlog.get_logger(__name__)

FEEDS: Final = (
    "https://www.federalreserve.gov/feeds/press_monetary.xml",
    "https://www.federalreserve.gov/feeds/press_all.xml",
    "https://www.federalreserve.gov/feeds/speeches.xml",
)
POLL_SECONDS: Final = 900
MAX_HEADLINE: Final = 500
MAX_SNIPPET: Final = 2000
HEADERS: Final = {"User-Agent": "personal-research-archive/0.1"}


@dataclass(frozen=True)
class FeedItem:
    headline: str
    url: str
    snippet: str | None
    published_at: datetime

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(f"{self.headline}\n{self.snippet}".encode()).hexdigest()


class FeedError(ValueError):
    """A feed that cannot be trusted. It is skipped and tried again later."""


def parse_feed(document: bytes | str) -> list[FeedItem]:
    """Parse RSS. An item missing a title, link or date is skipped, never guessed at."""
    try:
        root = SafeXml.fromstring(document)
    except (ParseError, DefusedXmlException, ValueError) as error:
        raise FeedError(type(error).__name__) from error
    items: list[FeedItem] = []
    for node in root.iter("item"):
        title = clean_text(node.findtext("title") or "")
        link = (node.findtext("link") or "").strip()
        published = (node.findtext("pubDate") or "").strip()
        if not title or not link.startswith("https://") or not published:
            continue
        try:
            at = ensure_utc(parsedate_to_datetime(published))
        except TypeError, ValueError:
            continue
        description = clean_text(node.findtext("description") or "")
        items.append(FeedItem(title[:MAX_HEADLINE], link, description[:MAX_SNIPPET] or None, at))
    return items


class NewsArchive:
    def __init__(self, engine: AsyncEngine, provider_id: int, source_id: int) -> None:
        self._engine = engine
        self._provider_id = provider_id
        self._source_id = source_id

    async def store(self, items: Sequence[FeedItem], now: datetime) -> int:
        """Keep the first sighting of each URL. Returns how many were new."""
        if not items:
            return 0
        rows = [
            {
                "provider": self._provider_id,
                "source": self._source_id,
                "headline": item.headline,
                "url": item.url,
                "snippet": item.snippet,
                "published": item.published_at,
                "now": now,
                "hash": item.content_hash,
            }
            for item in items
        ]
        count = text("SELECT count(*) FROM news_articles WHERE provider_id = :provider")
        insert = text(
            """INSERT INTO news_articles (provider_id, source_id, headline, url, snippet,
                 published_at, retrieved_at, first_seen_at, content_hash)
               VALUES (:provider, :source, :headline, :url, :snippet, :published, :now, :now,
                 :hash)
               ON CONFLICT (provider_id, url) DO NOTHING"""
        )
        async with self._engine.begin() as connection:
            before = (await connection.execute(count, {"provider": self._provider_id})).scalar_one()
            await connection.execute(insert, rows)
            after = (await connection.execute(count, {"provider": self._provider_id})).scalar_one()
        return int(after - before)


class OfficialSourceCollector:
    def __init__(
        self, archive: NewsArchive, clock: Clock, http: httpx.AsyncClient | None = None
    ) -> None:
        self._archive = archive
        self._clock = clock
        self._http = http or httpx.AsyncClient(timeout=20, headers=HEADERS)

    async def poll_once(self) -> int:
        """Read every feed. One bad feed never stops the others."""
        stored = 0
        for url in FEEDS:
            try:
                response = await self._http.get(url)
                response.raise_for_status()
                stored += await self._archive.store(parse_feed(response.content), self._clock.now())
            except (httpx.HTTPError, FeedError) as error:
                log.warning("feed_failed", feed=url, error=type(error).__name__)
        return stored

    async def run(self) -> None:
        while True:
            await self.poll_once()
            await asyncio.sleep(POLL_SECONDS)
