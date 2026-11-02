"""Indicator values and detected patterns."""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from trading_intel.domain.candles import Timeframe
from trading_intel.domain.patterns import DetectedPattern


def _decimal(value: float | None) -> Decimal | None:
    """Via the shortest text form, so a stored price keeps its original digits."""
    return None if value is None else Decimal(str(value))


@dataclass(frozen=True)
class StoredPattern:
    pattern_type: str
    direction: str
    timeframe: Timeframe
    price_level: Decimal | None
    zone_low: Decimal | None
    zone_high: Decimal | None
    formed_at: datetime
    detected_at: datetime
    validation_status: str
    invalidated_at: datetime | None
    strength_score: Decimal | None
    evidence: dict[str, Any]


class AnalysisRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def store_indicators(
        self,
        provider_id: int,
        instrument_id: int,
        timeframe: Timeframe,
        close_time: datetime,
        version: str,
        values: dict[str, float | None],
    ) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    """INSERT INTO technical_indicators (provider_id, instrument_id, timeframe,
                         close_time, feature_set_version, values)
                       VALUES (:provider, :instrument, CAST(:timeframe AS timeframe_t), :at,
                         :version, CAST(:values AS jsonb))
                       ON CONFLICT (provider_id, instrument_id, timeframe, close_time,
                         feature_set_version)
                       DO UPDATE SET values = EXCLUDED.values, computed_at = now()"""
                ),
                {
                    "provider": provider_id,
                    "instrument": instrument_id,
                    "timeframe": timeframe,
                    "at": close_time,
                    "version": version,
                    "values": json.dumps(values),
                },
            )

    async def latest_indicators(
        self, provider_id: int, instrument_id: int, timeframe: Timeframe, as_of: datetime
    ) -> tuple[datetime, dict[str, float | None]] | None:
        async with self._engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        """SELECT close_time, values FROM technical_indicators
                           WHERE provider_id = :provider AND instrument_id = :instrument
                             AND timeframe = CAST(:timeframe AS timeframe_t)
                             AND close_time <= :as_of
                           ORDER BY close_time DESC LIMIT 1"""
                    ),
                    {
                        "provider": provider_id,
                        "instrument": instrument_id,
                        "timeframe": timeframe,
                        "as_of": as_of,
                    },
                )
            ).one_or_none()
        return (row.close_time, row.values) if row else None

    async def store_patterns(
        self,
        provider_id: int,
        instrument_id: int,
        timeframe: Timeframe,
        patterns: Sequence[DetectedPattern],
    ) -> None:
        """Insert new patterns. A repeat may only record that the pattern was invalidated."""
        if not patterns:
            return
        rows = [
            {
                "provider": provider_id,
                "instrument": instrument_id,
                "timeframe": timeframe,
                "pattern_type": p.pattern_type,
                "direction": p.direction.value,
                "price_level": _decimal(p.price_level),
                "zone_low": _decimal(p.zone_low),
                "zone_high": _decimal(p.zone_high),
                "formed_at": p.formed_at,
                "detected_at": p.detected_at,
                "status": p.status,
                "invalidated_at": p.invalidated_at,
                "strength": Decimal(str(p.strength)),
                "rule_version": p.rule_version,
                "evidence": json.dumps(p.evidence),
            }
            for p in patterns
        ]
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    """INSERT INTO detected_patterns (provider_id, instrument_id, timeframe,
                         pattern_type, direction, price_level, zone_low, zone_high, formed_at,
                         detected_at, validation_status, invalidated_at, strength_score,
                         rule_version, evidence)
                       VALUES (:provider, :instrument, CAST(:timeframe AS timeframe_t),
                         :pattern_type, :direction, :price_level, :zone_low, :zone_high,
                         :formed_at, :detected_at, :status, :invalidated_at, :strength,
                         :rule_version, CAST(:evidence AS jsonb))
                       ON CONFLICT (provider_id, instrument_id, timeframe, pattern_type,
                         direction, formed_at, detected_at, rule_version)
                       DO UPDATE SET validation_status = EXCLUDED.validation_status,
                         invalidated_at = EXCLUDED.invalidated_at"""
                ),
                rows,
            )

    async def recent_patterns(
        self,
        provider_id: int,
        instrument_id: int,
        timeframe: Timeframe,
        as_of: datetime,
        limit: int = 50,
    ) -> list[StoredPattern]:
        query = text(
            """SELECT pattern_type, direction, timeframe::text AS timeframe, price_level,
                      zone_low, zone_high, formed_at, detected_at, validation_status,
                      invalidated_at, strength_score, evidence
               FROM detected_patterns
               WHERE provider_id = :provider AND instrument_id = :instrument
                 AND timeframe = CAST(:timeframe AS timeframe_t) AND detected_at <= :as_of
               ORDER BY detected_at DESC LIMIT :limit"""
        )
        params = {
            "provider": provider_id,
            "instrument": instrument_id,
            "timeframe": timeframe,
            "as_of": as_of,
            "limit": limit,
        }
        async with self._engine.connect() as connection:
            rows = (await connection.execute(query, params)).mappings().all()
        return [StoredPattern(**{**row, "timeframe": Timeframe(row["timeframe"])}) for row in rows]
