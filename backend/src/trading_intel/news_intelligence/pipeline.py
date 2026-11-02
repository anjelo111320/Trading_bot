"""Cluster, score and classify stored news. Costs are controlled before any model call."""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final
from uuid import uuid7

import structlog
from pydantic import ValidationError

from trading_intel.core.clock import Clock
from trading_intel.database.repositories.news import NewsRepository, StoredArticle
from trading_intel.domain.candles import Timeframe
from trading_intel.domain.instruments import Instrument
from trading_intel.news_intelligence.classifier import (
    MODEL,
    OUTPUT_SCHEMA_VERSION,
    PROMPT_BODY,
    PROMPT_NAME,
    PROMPT_SHA256,
    PROMPT_VERSION,
    Classifier,
    cost_usd,
)
from trading_intel.news_intelligence.normalize import same_story
from trading_intel.news_intelligence.relevance import assess_relevance

log = structlog.get_logger(__name__)

DAILY_LIMIT_USD: Final = Decimal(3)
BATCH_LIMIT: Final = 10


@dataclass(frozen=True)
class PipelineResult:
    clustered: int
    classified: int
    skipped_budget: int
    invalid: int


class NewsPipeline:
    def __init__(
        self,
        news: NewsRepository,
        instruments: Sequence[Instrument],
        clock: Clock,
        classifier: Classifier | None = None,
        daily_limit: Decimal = DAILY_LIMIT_USD,
    ) -> None:
        self._news = news
        self._instruments = instruments
        self._clock = clock
        self._classifier = classifier
        self._daily_limit = daily_limit

    async def cluster_and_score(self) -> int:
        """Group repeats of one story, and link each item to the assets it concerns."""
        pending = await self._news.unclustered()
        known = await self._news.recent_clusters()
        for article in sorted(pending, key=lambda a: a.published_at):
            match = next(
                (
                    k
                    for k in known
                    if same_story(
                        article.headline, article.published_at, k.headline, k.published_at
                    )
                ),
                None,
            )
            cluster = match.cluster_id if match and match.cluster_id else uuid7()
            await self._news.set_cluster(article.id, cluster)
            known.append(
                StoredArticle(
                    article.id,
                    article.headline,
                    article.snippet,
                    article.published_at,
                    article.first_seen_at,
                    cluster,
                )
            )
            relevance = assess_relevance(article.headline, article.snippet)
            for instrument in self._instruments:
                score = relevance.assets.get(instrument.base_asset)
                if score is not None:
                    await self._news.link_instrument(article.id, instrument.id, score)
        return len(pending)

    async def classify_pending(self) -> tuple[int, int, int]:
        """Each story is classified once, and the daily limit is checked before every call."""
        if self._classifier is None:
            return 0, 0, 0
        prompt = await self._news.ensure_prompt(
            PROMPT_NAME, PROMPT_VERSION, PROMPT_SHA256, PROMPT_BODY, OUTPUT_SCHEMA_VERSION
        )
        prices = await self._news.model_prices(MODEL, self._clock.now())
        if prices is None:
            log.error("model_price_missing", model=MODEL)
            return 0, 0, 0
        classified = skipped = invalid = 0
        day_start = Timeframe.D1.floor(self._clock.now())
        for article in await self._news.awaiting_classification(BATCH_LIMIT):
            if await self._news.spent_since(day_start) >= self._daily_limit:
                skipped += 1
                continue
            result = await self._classifier.classify(article.headline, article.snippet)
            usage = result.usage
            await self._news.record_usage(
                "news_classification",
                result.model,
                usage.input_tokens,
                usage.output_tokens,
                usage.cache_read_tokens,
                usage.cache_write_5m_tokens,
                cost_usd(usage, prices),
            )
            if result.status != "valid" or result.assessment is None:
                invalid += 1
                continue
            await self._news.store_classification(
                article.id,
                prompt,
                result.model,
                result.assessment.model_dump(),
                self._clock.now(),
            )
            classified += 1
        return classified, skipped, invalid

    async def run_once(self) -> PipelineResult:
        clustered = await self.cluster_and_score()
        try:
            classified, skipped, invalid = await self.classify_pending()
        except ValidationError:
            log.warning("classification_rejected")
            return PipelineResult(clustered, 0, 0, 1)
        return PipelineResult(clustered, classified, skipped, invalid)
