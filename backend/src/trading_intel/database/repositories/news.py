"""News, classifications and API usage."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid7

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


@dataclass(frozen=True)
class StoredArticle:
    id: UUID
    headline: str
    snippet: str | None
    published_at: datetime
    first_seen_at: datetime
    cluster_id: UUID | None


class NewsRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def unclustered(self, limit: int = 200) -> list[StoredArticle]:
        return await self._read("cluster_id IS NULL", limit)

    async def recent_clusters(self, limit: int = 500) -> list[StoredArticle]:
        return await self._read("cluster_id IS NOT NULL", limit)

    async def _read(self, condition: str, limit: int) -> list[StoredArticle]:
        query = text(
            f"""SELECT id, headline, snippet, published_at, first_seen_at, cluster_id
                FROM news_articles WHERE {condition}
                ORDER BY published_at DESC LIMIT :limit"""  # noqa: S608
        )
        async with self._engine.connect() as connection:
            rows = (await connection.execute(query, {"limit": limit})).mappings().all()
        return [StoredArticle(**row) for row in rows]

    async def set_cluster(self, article_id: UUID, cluster_id: UUID) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                text("UPDATE news_articles SET cluster_id = :cluster WHERE id = :id"),
                {"id": article_id, "cluster": cluster_id},
            )

    async def link_instrument(self, article_id: UUID, instrument_id: int, score: float) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    """INSERT INTO news_article_instruments (article_id, instrument_id,
                         relevance_score)
                       VALUES (:article, :instrument, :score)
                       ON CONFLICT (article_id, instrument_id) DO NOTHING"""
                ),
                {"article": article_id, "instrument": instrument_id, "score": score},
            )

    async def awaiting_classification(self, limit: int) -> list[StoredArticle]:
        """One article per story that is relevant and has no classification in that story."""
        query = text(
            """SELECT DISTINCT ON (a.cluster_id) a.id, a.headline, a.snippet, a.published_at,
                      a.first_seen_at, a.cluster_id
               FROM news_articles a
               WHERE a.cluster_id IS NOT NULL
                 AND EXISTS (SELECT 1 FROM news_article_instruments l WHERE l.article_id = a.id)
                 AND NOT EXISTS (
                   SELECT 1 FROM news_classifications c
                   JOIN news_articles b ON b.id = c.article_id
                   WHERE b.cluster_id = a.cluster_id)
               ORDER BY a.cluster_id, a.published_at
               LIMIT :limit"""
        )
        async with self._engine.connect() as connection:
            rows = (await connection.execute(query, {"limit": limit})).mappings().all()
        return [StoredArticle(**row) for row in rows]

    async def ensure_prompt(
        self, name: str, version: int, sha: str, body: str, schema: int
    ) -> UUID:
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    """INSERT INTO prompt_versions (name, version, sha256, body,
                         output_schema_version)
                       VALUES (:name, :version, :sha, :body, :schema)
                       ON CONFLICT (name, version) DO NOTHING"""
                ),
                {"name": name, "version": version, "sha": sha, "body": body, "schema": schema},
            )
            found: UUID = (
                await connection.execute(
                    text(
                        "SELECT id FROM prompt_versions WHERE name = :name AND version = :version"
                    ),
                    {"name": name, "version": version},
                )
            ).scalar_one()
        return found

    async def store_classification(
        self,
        article_id: UUID,
        prompt_id: UUID,
        model: str,
        values: dict[str, Any],
        classified_at: datetime,
    ) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    """INSERT INTO news_classifications (id, article_id, prompt_version_id, model,
                         event_type, sentiment, potential_impact, certainty, possibly_misleading,
                         ai_summary, classified_at)
                       VALUES (:id, :article, :prompt, :model, :event_type, :sentiment,
                         :potential_impact, :certainty, :possibly_misleading, :summary, :at)"""
                ),
                {
                    "id": uuid7(),
                    "article": article_id,
                    "prompt": prompt_id,
                    "model": model,
                    "at": classified_at,
                    **values,
                },
            )

    async def model_prices(self, model: str, at: datetime) -> dict[str, Decimal] | None:
        async with self._engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        """SELECT input_per_mtok, output_per_mtok, cache_read_per_mtok,
                                  cache_write_5m_per_mtok FROM ai_model_prices
                           WHERE model = :model AND effective_from <= :at
                           ORDER BY effective_from DESC LIMIT 1"""
                    ),
                    {"model": model, "at": at},
                )
            ).one_or_none()
        if row is None:
            return None
        return {
            "input": row.input_per_mtok,
            "output": row.output_per_mtok,
            "cache_read": row.cache_read_per_mtok,
            "cache_write_5m": row.cache_write_5m_per_mtok,
        }

    async def record_usage(
        self,
        purpose: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_read: int,
        cache_write: int,
        cost: Decimal,
    ) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    """INSERT INTO api_usage (provider_id, purpose, route, model, input_tokens,
                         output_tokens, cache_read_tokens, cache_write_5m_tokens, cost_usd)
                       SELECT id, :purpose, 'classification', :model, :input, :output, :read,
                         :write, :cost FROM providers WHERE code = 'anthropic'"""
                ),
                {
                    "purpose": purpose,
                    "model": model,
                    "input": input_tokens,
                    "output": output_tokens,
                    "read": cache_read,
                    "write": cache_write,
                    "cost": cost,
                },
            )

    async def spent_since(self, moment: datetime) -> Decimal:
        async with self._engine.connect() as connection:
            value: Decimal = (
                await connection.execute(
                    text(
                        "SELECT COALESCE(sum(cost_usd), 0) FROM api_usage "
                        "WHERE occurred_at >= :moment"
                    ),
                    {"moment": moment},
                )
            ).scalar_one()
        return value

    async def visible_at(self, moment: datetime, limit: int = 50) -> list[dict[str, Any]]:
        """News as it could be known then: the later of publication and first sighting."""
        query = text(
            """SELECT a.id, a.headline, a.url, a.published_at, a.retrieved_at, a.first_seen_at,
                      s.name AS source, s.credibility_tier,
                      c.event_type, c.sentiment, c.potential_impact, c.certainty,
                      c.possibly_misleading, c.ai_summary, c.model,
                      (SELECT max(l.relevance_score) FROM news_article_instruments l
                       WHERE l.article_id = a.id) AS relevance
               FROM news_articles a
               LEFT JOIN news_sources s ON s.id = a.source_id
               LEFT JOIN LATERAL (
                 SELECT * FROM news_classifications x JOIN news_articles b ON b.id = x.article_id
                 WHERE b.cluster_id = a.cluster_id AND x.classified_at <= :moment
                 ORDER BY x.classified_at DESC LIMIT 1
               ) c ON true
               WHERE GREATEST(a.published_at, a.first_seen_at) <= :moment
               ORDER BY a.published_at DESC LIMIT :limit"""
        )
        async with self._engine.connect() as connection:
            rows = (
                (await connection.execute(query, {"moment": moment, "limit": limit}))
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]
