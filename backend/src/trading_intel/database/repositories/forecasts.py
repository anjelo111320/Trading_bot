"""Model forecasts and their outcomes. Each is written once and never changed (D040).

A forecast is stored before its outcome is known, and the database refuses later edits, so
a track record cannot be improved after the fact.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncEngine

from trading_intel.domain.candles import Timeframe

Reason = Literal["setup", "manual", "study"]

MODEL_PROVIDER = "kronos"


@dataclass(frozen=True)
class ForecastKey:
    provider_id: int
    instrument_id: int
    timeframe: Timeframe
    as_of: datetime
    horizon_candles: int
    model: str
    model_revision: str
    seed: int


@dataclass(frozen=True)
class NewForecast:
    key: ForecastKey
    tokenizer: str
    tokenizer_revision: str
    code_revision: str
    context_candles: int
    reason: Reason
    last_close: Decimal
    atr: float
    paths: list[Any]
    summary: dict[str, Any]
    baseline: dict[str, Any]
    runtime_ms: int


@dataclass(frozen=True)
class StoredForecast:
    id: UUID
    key: ForecastKey
    reason: Reason
    last_close: Decimal
    atr: float
    summary: dict[str, Any]
    baseline: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True)
class ResolvedScores:
    reason: Reason
    model_score: dict[str, Any]
    baseline_score: dict[str, Any]


_SELECT = """SELECT id, provider_id, instrument_id, timeframe, as_of, horizon_candles, model,
                    model_revision, seed, reason, last_close, atr, summary, baseline, created_at
             FROM model_forecasts f"""


def _stored(row: RowMapping) -> StoredForecast:
    return StoredForecast(
        id=row["id"],
        key=ForecastKey(
            provider_id=row["provider_id"],
            instrument_id=row["instrument_id"],
            timeframe=Timeframe(row["timeframe"]),
            as_of=row["as_of"],
            horizon_candles=row["horizon_candles"],
            model=row["model"],
            model_revision=row["model_revision"],
            seed=row["seed"],
        ),
        reason=row["reason"],
        last_close=row["last_close"],
        atr=row["atr"],
        summary=row["summary"],
        baseline=row["baseline"],
        created_at=row["created_at"],
    )


class ForecastRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def find(self, key: ForecastKey) -> StoredForecast | None:
        query = text(
            f"""{_SELECT}
                WHERE provider_id = :provider AND instrument_id = :instrument
                  AND timeframe = CAST(:timeframe AS timeframe_t) AND as_of = :as_of
                  AND horizon_candles = :horizon AND model = :model
                  AND model_revision = :revision AND seed = :seed"""
        )
        async with self._engine.connect() as connection:
            row = (await connection.execute(query, _key(key))).mappings().one_or_none()
        return _stored(row) if row else None

    async def store(self, forecast: NewForecast) -> StoredForecast:
        """Insert once. Storing the same forecast again returns the first one unchanged."""
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    """INSERT INTO model_forecasts (provider_id, instrument_id, timeframe, as_of,
                         horizon_candles, model_provider_id, model, model_revision, tokenizer,
                         tokenizer_revision, code_revision, seed, context_candles, reason,
                         last_close, atr, paths, summary, baseline, runtime_ms)
                       SELECT :provider, :instrument, CAST(:timeframe AS timeframe_t), :as_of,
                         :horizon, p.id, :model, :revision, :tokenizer, :tokenizer_revision,
                         :code_revision, :seed, :context, :reason, :last_close, :atr,
                         CAST(:paths AS jsonb), CAST(:summary AS jsonb),
                         CAST(:baseline AS jsonb), :runtime
                       FROM providers p WHERE p.code = :model_provider
                       ON CONFLICT DO NOTHING"""
                ),
                {
                    **_key(forecast.key),
                    "model_provider": MODEL_PROVIDER,
                    "tokenizer": forecast.tokenizer,
                    "tokenizer_revision": forecast.tokenizer_revision,
                    "code_revision": forecast.code_revision,
                    "context": forecast.context_candles,
                    "reason": forecast.reason,
                    "last_close": forecast.last_close,
                    "atr": forecast.atr,
                    "paths": json.dumps(forecast.paths),
                    "summary": json.dumps(forecast.summary),
                    "baseline": json.dumps(forecast.baseline),
                    "runtime": forecast.runtime_ms,
                },
            )
        stored = await self.find(forecast.key)
        if stored is None:
            raise LookupError(f"the {MODEL_PROVIDER} provider row is missing")
        return stored

    async def unresolved(self) -> list[StoredForecast]:
        query = text(
            f"""{_SELECT}
                WHERE NOT EXISTS (
                  SELECT 1 FROM model_forecast_outcomes o WHERE o.forecast_id = f.id)
                ORDER BY as_of"""  # noqa: S608
        )
        async with self._engine.connect() as connection:
            rows = (await connection.execute(query)).mappings().all()
        return [_stored(row) for row in rows]

    async def store_outcome(
        self,
        forecast_id: UUID,
        realized: tuple[Decimal, Decimal, Decimal],
        model_score: dict[str, Any],
        baseline_score: dict[str, Any],
    ) -> bool:
        """Record what happened. Returns False if the forecast was already resolved."""
        high, low, close = realized
        async with self._engine.begin() as connection:
            result = await connection.execute(
                text(
                    """INSERT INTO model_forecast_outcomes (forecast_id, realized_high,
                         realized_low, realized_close, model_score, baseline_score)
                       VALUES (:id, :high, :low, :close, CAST(:model AS jsonb),
                         CAST(:baseline AS jsonb))
                       ON CONFLICT (forecast_id) DO NOTHING"""
                ),
                {
                    "id": forecast_id,
                    "high": high,
                    "low": low,
                    "close": close,
                    "model": json.dumps(model_score),
                    "baseline": json.dumps(baseline_score),
                },
            )
        return bool(result.rowcount)

    async def resolved(
        self,
        *,
        model: str,
        model_revision: str,
        timeframe: Timeframe,
        horizon_candles: int,
        reasons: Sequence[Reason],
        instrument_id: int | None = None,
    ) -> list[ResolvedScores]:
        query = text(
            """SELECT f.reason, o.model_score, o.baseline_score
               FROM model_forecasts f JOIN model_forecast_outcomes o ON o.forecast_id = f.id
               WHERE f.model = :model AND f.model_revision = :revision
                 AND f.timeframe = CAST(:timeframe AS timeframe_t)
                 AND f.horizon_candles = :horizon AND f.reason = ANY(:reasons)
                 AND (CAST(:instrument AS integer) IS NULL OR f.instrument_id = :instrument)
               ORDER BY f.as_of"""
        )
        params = {
            "model": model,
            "revision": model_revision,
            "timeframe": timeframe,
            "horizon": horizon_candles,
            "reasons": list(reasons),
            "instrument": instrument_id,
        }
        async with self._engine.connect() as connection:
            rows = (await connection.execute(query, params)).mappings().all()
        return [
            ResolvedScores(row["reason"], row["model_score"], row["baseline_score"]) for row in rows
        ]


def _key(key: ForecastKey) -> dict[str, Any]:
    return {
        "provider": key.provider_id,
        "instrument": key.instrument_id,
        "timeframe": key.timeframe,
        "as_of": key.as_of,
        "horizon": key.horizon_candles,
        "model": key.model,
        "revision": key.model_revision,
        "seed": key.seed,
    }
