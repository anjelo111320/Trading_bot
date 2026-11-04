"""Backtest run records. The schema allows one holdout run per strategy configuration (D029)."""

import hashlib
import json
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from trading_intel.core.errors import AppError


class HoldoutAlreadyUsedError(AppError):
    code = "holdout_already_used"


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, default=str)


class BacktestRunRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def ensure_dataset(self, name: str, manifest: dict[str, Any]) -> UUID:
        body = _json(manifest)
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    """INSERT INTO dataset_versions (name, manifest, content_sha256)
                       VALUES (:name, CAST(:body AS jsonb), :digest)
                       ON CONFLICT (name) DO NOTHING"""
                ),
                {"name": name, "body": body, "digest": hashlib.sha256(body.encode()).hexdigest()},
            )
            found: UUID = (
                await connection.execute(
                    text("SELECT id FROM dataset_versions WHERE name = :name"), {"name": name}
                )
            ).scalar_one()
        return found

    async def start_holdout(
        self,
        strategy_id: UUID,
        dataset_id: UUID,
        window: tuple[datetime, datetime],
        cost_model: dict[str, Any],
        git_sha: str,
    ) -> UUID:
        """Claim the strategy's single holdout run. A second claim is refused by the database."""
        try:
            async with self._engine.begin() as connection:
                found: UUID = (
                    await connection.execute(
                        text(
                            """INSERT INTO backtest_runs (strategy_configuration_id,
                                 dataset_version_id, split, window_start, window_end,
                                 cost_model, git_sha, seed, trial_number)
                               VALUES (:strategy, :dataset, 'holdout', :start, :end,
                                 CAST(:costs AS jsonb), :sha, 0, 1)
                               RETURNING id"""
                        ),
                        {
                            "strategy": strategy_id,
                            "dataset": dataset_id,
                            "start": window[0],
                            "end": window[1],
                            "costs": _json(cost_model),
                            "sha": git_sha,
                        },
                    )
                ).scalar_one()
        except IntegrityError as error:
            raise HoldoutAlreadyUsedError(
                "this strategy configuration has already used its holdout run"
            ) from error
        return found

    async def finish(
        self, run_id: UUID, status: Literal["succeeded", "failed"], metrics: dict[str, Any]
    ) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    """UPDATE backtest_runs
                       SET status = :status, metrics = CAST(:metrics AS jsonb), finished_at = now()
                       WHERE id = :id"""
                ),
                {"id": run_id, "status": status, "metrics": _json(metrics)},
            )
