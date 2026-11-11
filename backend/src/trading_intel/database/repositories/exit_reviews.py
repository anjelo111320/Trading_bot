"""Claude's exit advice on paper trades, in shadow mode (D051).

A row is added once per trade and 15M close where a check fired, and scored once after the
trade closes. Rows never change a trade.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


@dataclass(frozen=True)
class NewReview:
    position_id: UUID
    account_id: UUID
    symbol: str
    strategy: str
    close_time: datetime
    checks: tuple[str, ...]
    targets_hit: int
    best_at: datetime | None
    price: Decimal
    progress_r: Decimal
    facts: str
    status: str
    prompt_version_id: UUID | None = None
    model: str | None = None
    action: str | None = None
    reason: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal(0)
    reply: str | None = None


@dataclass(frozen=True)
class StoredReview:
    checks: tuple[str, ...]
    targets_hit: int
    best_at: datetime | None
    close_time: datetime


@dataclass(frozen=True)
class Unscored:
    id: UUID
    position_id: UUID
    close_time: datetime
    action: str


class ExitReviewRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def record(self, review: NewReview) -> bool:
        """False if this trade already has a review at this close, as after a restart."""
        async with self._engine.begin() as connection:
            result = await connection.execute(
                text(
                    """INSERT INTO ai_exit_reviews (position_id, account_id, symbol, strategy,
                         close_time, checks, targets_hit, best_at, price, progress_r, facts,
                         status, prompt_version_id, model, action, reason, input_tokens,
                         output_tokens, cost_usd, reply)
                       VALUES (:position_id, :account_id, :symbol, :strategy, :close_time,
                         :checks, :targets_hit, :best_at, :price, :progress_r, :facts, :status,
                         :prompt_version_id, :model, :action, :reason, :input_tokens,
                         :output_tokens, :cost_usd, :reply)
                       ON CONFLICT (position_id, close_time) DO NOTHING"""
                ),
                {**review.__dict__, "checks": list(review.checks)},
            )
        return result.rowcount == 1

    async def prior(self, position_id: UUID) -> list[StoredReview]:
        async with self._engine.connect() as connection:
            rows = (
                await connection.execute(
                    text(
                        """SELECT checks, targets_hit, best_at, close_time FROM ai_exit_reviews
                           WHERE position_id = :position ORDER BY close_time"""
                    ),
                    {"position": position_id},
                )
            ).all()
        return [StoredReview(tuple(r.checks), r.targets_hit, r.best_at, r.close_time) for r in rows]

    async def unscored(self) -> list[Unscored]:
        """Advice on trades that have finished, not yet scored."""
        async with self._engine.connect() as connection:
            rows = (
                await connection.execute(
                    text(
                        """SELECT e.id, e.position_id, e.close_time, e.action
                           FROM ai_exit_reviews e
                           JOIN paper_positions p ON p.id = e.position_id
                           WHERE e.status = 'advised' AND e.scored_at IS NULL
                             AND p.status IN ('closed', 'cancelled')
                           ORDER BY e.position_id, e.close_time"""
                    )
                )
            ).all()
        return [Unscored(r.id, r.position_id, r.close_time, r.action) for r in rows]

    async def score(
        self, review_id: UUID, own_r: Decimal, advised_r: Decimal, at: datetime
    ) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    """UPDATE ai_exit_reviews SET own_r = :own, advised_r = :advised,
                         scored_at = :at WHERE id = :id AND scored_at IS NULL"""
                ),
                {"id": review_id, "own": own_r, "advised": advised_r, "at": at},
            )

    async def account_names(self) -> dict[UUID, str]:
        async with self._engine.connect() as connection:
            rows = (await connection.execute(text("SELECT id, name FROM trading_accounts"))).all()
        return {row.id: row.name for row in rows}

    async def summary(self) -> dict[str, Any]:
        """Counts by status, total cost, and the scored answers that were not "hold"."""
        async with self._engine.connect() as connection:
            statuses = (
                await connection.execute(
                    text("SELECT status, count(*) AS n FROM ai_exit_reviews GROUP BY status")
                )
            ).all()
            row = (
                await connection.execute(
                    text(
                        """SELECT COALESCE(sum(cost_usd), 0) AS cost,
                                  count(*) FILTER (WHERE scored_at IS NOT NULL) AS scored,
                                  count(*) FILTER (WHERE scored_at IS NOT NULL
                                                   AND action <> 'hold') AS acted,
                                  avg(advised_r - own_r) FILTER (WHERE scored_at IS NOT NULL
                                                   AND action <> 'hold') AS change
                           FROM ai_exit_reviews"""
                    )
                )
            ).one()
        return {
            "statuses": {r.status: r.n for r in statuses},
            "cost": row.cost,
            "scored": row.scored,
            "acted": row.acted,
            "change": row.change,
        }

    async def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        async with self._engine.connect() as connection:
            rows = (
                await connection.execute(
                    text(
                        """SELECT e.close_time, e.symbol, e.strategy, a.name AS account,
                                  e.checks, e.status, e.action, e.reason, e.progress_r,
                                  e.price, e.model, e.input_tokens, e.output_tokens,
                                  e.cost_usd, e.own_r, e.advised_r, e.scored_at
                           FROM ai_exit_reviews e
                           JOIN trading_accounts a ON a.id = e.account_id
                           ORDER BY e.close_time DESC, e.symbol LIMIT :limit"""
                    ),
                    {"limit": limit},
                )
            ).all()
        return [dict(row._mapping) for row in rows]
