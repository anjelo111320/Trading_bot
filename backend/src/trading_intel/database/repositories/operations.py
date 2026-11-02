"""Ingest runs, gaps, rule snapshots, market snapshots and system events."""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from trading_intel.domain.base import DataOrigin
from trading_intel.domain.candles import Timeframe
from trading_intel.domain.instruments import InstrumentRules
from trading_intel.domain.market import FundingRate, LiquidationSample

GapState = Literal["detected", "repairing", "repaired", "provider_missing"]
RunKind = Literal["backfill", "live", "repair", "reconcile"]
Severity = Literal["debug", "info", "warning", "error", "critical"]


@dataclass(frozen=True)
class GapRecord:
    id: UUID
    provider_id: int
    instrument_id: int
    timeframe: Timeframe
    gap_start: datetime
    gap_end: datetime
    state: GapState
    cause: str | None
    detected_at: datetime
    resolved_at: datetime | None


@dataclass(frozen=True)
class SnapshotRow:
    provider_id: int
    instrument_id: int
    minute_start: datetime
    best_bid: Decimal | None
    best_ask: Decimal | None
    spread_min: Decimal | None
    spread_mean: Decimal | None
    spread_max: Decimal | None
    spread_last: Decimal | None
    sample_count: int
    crossed_book_count: int
    data_origin: DataOrigin
    received_at: datetime
    mark_price: Decimal | None = None
    index_price: Decimal | None = None
    open_interest: Decimal | None = None


class RunRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def start(self, provider_id: int, kind: RunKind, git_sha: str) -> UUID:
        async with self._engine.begin() as connection:
            result = await connection.execute(
                text(
                    """INSERT INTO ingest_runs (provider_id, kind, git_sha)
                       VALUES (:provider, :kind, :sha) RETURNING id"""
                ),
                {"provider": provider_id, "kind": kind, "sha": git_sha},
            )
            run_id: UUID = result.scalar_one()
        return run_id

    async def finish(
        self, run_id: UUID, status: Literal["succeeded", "failed"], stats: dict[str, Any]
    ) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    """UPDATE ingest_runs SET finished_at = now(), status = :status,
                         stats = CAST(:stats AS jsonb) WHERE id = :id"""
                ),
                {"id": run_id, "status": status, "stats": json.dumps(stats)},
            )


class GapRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def record(
        self,
        provider_id: int,
        instrument_id: int,
        timeframe: Timeframe,
        gap_start: datetime,
        gap_end: datetime,
        cause: str,
    ) -> None:
        """Record a gap once. The same start is the same gap."""
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    """INSERT INTO market_gaps (provider_id, instrument_id, timeframe, gap_start,
                         gap_end, cause)
                       VALUES (:provider, :instrument, CAST(:timeframe AS timeframe_t), :start,
                         :end, :cause)
                       ON CONFLICT (provider_id, instrument_id, timeframe, gap_start)
                       DO UPDATE SET gap_end = GREATEST(market_gaps.gap_end, EXCLUDED.gap_end)"""
                ),
                {
                    "provider": provider_id,
                    "instrument": instrument_id,
                    "timeframe": timeframe,
                    "start": gap_start,
                    "end": gap_end,
                    "cause": cause,
                },
            )

    async def set_state(
        self,
        provider_id: int,
        instrument_id: int,
        timeframe: Timeframe,
        gap_start: datetime,
        state: GapState,
        resolved_at: datetime | None = None,
    ) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    """UPDATE market_gaps SET state = CAST(:state AS gap_state_t),
                         resolved_at = :resolved
                       WHERE provider_id = :provider AND instrument_id = :instrument
                         AND timeframe = CAST(:timeframe AS timeframe_t)
                         AND gap_start = :start"""
                ),
                {
                    "state": state,
                    "resolved": resolved_at,
                    "provider": provider_id,
                    "instrument": instrument_id,
                    "timeframe": timeframe,
                    "start": gap_start,
                },
            )

    async def list(
        self,
        *,
        provider_id: int | None = None,
        instrument_id: int | None = None,
        states: tuple[GapState, ...] | None = None,
        limit: int = 500,
    ) -> list[GapRecord]:
        query = text(
            """SELECT id, provider_id, instrument_id, timeframe::text AS timeframe, gap_start,
                      gap_end, state::text AS state, cause, detected_at, resolved_at
               FROM market_gaps
               WHERE (CAST(:provider AS smallint) IS NULL OR provider_id = :provider)
                 AND (CAST(:instrument AS integer) IS NULL OR instrument_id = :instrument)
                 AND (CAST(:states AS text[]) IS NULL OR state::text = ANY(:states))
               ORDER BY gap_start DESC LIMIT :limit"""
        )
        params = {
            "provider": provider_id,
            "instrument": instrument_id,
            "states": list(states) if states else None,
            "limit": limit,
        }
        async with self._engine.connect() as connection:
            rows = (await connection.execute(query, params)).mappings().all()
        return [GapRecord(**{**row, "timeframe": Timeframe(row["timeframe"])}) for row in rows]


class RuleRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def current(self, provider_id: int, instrument_id: int) -> InstrumentRules | None:
        return await self._read(provider_id, instrument_id, "valid_to IS NULL", {})

    async def as_of(
        self, provider_id: int, instrument_id: int, at: datetime
    ) -> InstrumentRules | None:
        return await self._read(
            provider_id,
            instrument_id,
            "valid_from <= :at AND (valid_to IS NULL OR valid_to > :at)",
            {"at": at},
        )

    async def _read(
        self, provider_id: int, instrument_id: int, condition: str, extra: dict[str, Any]
    ) -> InstrumentRules | None:
        query = text(
            f"""SELECT status, tick_size, lot_step, min_qty, max_qty, market_max_qty, min_notional,
                       max_notional, initial_margin_fraction, maintenance_margin_fraction, raw
                FROM instrument_rule_snapshots
                WHERE provider_id = :provider AND instrument_id = :instrument AND {condition}"""  # noqa: S608
        )
        params = {"provider": provider_id, "instrument": instrument_id, **extra}
        async with self._engine.connect() as connection:
            row = (await connection.execute(query, params)).mappings().one_or_none()
        return InstrumentRules(**row) if row else None

    async def replace_current(
        self, provider_id: int, instrument_id: int, rules: InstrumentRules, at: datetime
    ) -> None:
        """Close the current row and open a new one in one transaction."""
        key = {"provider": provider_id, "instrument": instrument_id}
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    """UPDATE instrument_rule_snapshots SET valid_to = :at
                       WHERE provider_id = :provider AND instrument_id = :instrument
                         AND valid_to IS NULL"""
                ),
                {**key, "at": at},
            )
            await connection.execute(
                text(
                    """INSERT INTO instrument_rule_snapshots (provider_id, instrument_id,
                         valid_from, status, tick_size, lot_step, min_qty, max_qty, market_max_qty,
                         min_notional, max_notional, initial_margin_fraction,
                         maintenance_margin_fraction, raw)
                       VALUES (:provider, :instrument, :at, :status, :tick_size, :lot_step,
                         :min_qty, :max_qty, :market_max_qty, :min_notional, :max_notional,
                         :initial_margin_fraction, :maintenance_margin_fraction,
                         CAST(:raw AS jsonb))"""
                ),
                {
                    **key,
                    "at": at,
                    **rules.model_dump(exclude={"raw"}),
                    "raw": json.dumps(rules.raw),
                },
            )


class SnapshotRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def upsert(self, row: SnapshotRow) -> None:
        await self.upsert_many([row])

    async def upsert_many(self, rows: Sequence[SnapshotRow]) -> None:
        """Keep one row per minute. A later writer may fill columns the first left empty."""
        if not rows:
            return
        query = text(
            """INSERT INTO market_snapshots (provider_id, instrument_id, minute_start, best_bid,
                 best_ask, spread_min, spread_mean, spread_max, spread_last, sample_count,
                 crossed_book_count, mark_price, index_price, open_interest, data_origin,
                 received_at)
               VALUES (:provider_id, :instrument_id, :minute_start, :best_bid, :best_ask,
                 :spread_min, :spread_mean, :spread_max, :spread_last, :sample_count,
                 :crossed_book_count, :mark_price, :index_price, :open_interest,
                 CAST(:data_origin AS data_origin_t), :received_at)
               ON CONFLICT (provider_id, instrument_id, minute_start) DO UPDATE SET
                 best_bid = COALESCE(EXCLUDED.best_bid, market_snapshots.best_bid),
                 best_ask = COALESCE(EXCLUDED.best_ask, market_snapshots.best_ask),
                 spread_min = COALESCE(EXCLUDED.spread_min, market_snapshots.spread_min),
                 spread_mean = COALESCE(EXCLUDED.spread_mean, market_snapshots.spread_mean),
                 spread_max = COALESCE(EXCLUDED.spread_max, market_snapshots.spread_max),
                 spread_last = COALESCE(EXCLUDED.spread_last, market_snapshots.spread_last),
                 sample_count = GREATEST(EXCLUDED.sample_count, market_snapshots.sample_count),
                 crossed_book_count = GREATEST(EXCLUDED.crossed_book_count,
                                               market_snapshots.crossed_book_count),
                 mark_price = COALESCE(EXCLUDED.mark_price, market_snapshots.mark_price),
                 index_price = COALESCE(EXCLUDED.index_price, market_snapshots.index_price),
                 open_interest = COALESCE(EXCLUDED.open_interest, market_snapshots.open_interest)"""
        )
        values = [{**row.__dict__, "data_origin": row.data_origin.value} for row in rows]
        async with self._engine.begin() as connection:
            await connection.execute(query, values)

    async def latest_book(
        self, provider_id: int, instrument_id: int, as_of: datetime
    ) -> tuple[datetime, Decimal, Decimal] | None:
        """The most recent recorded bid and ask, with the minute they belong to."""
        async with self._engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        """SELECT minute_start, best_bid, best_ask FROM market_snapshots
                           WHERE provider_id = :provider AND instrument_id = :instrument
                             AND minute_start <= :as_of AND best_bid IS NOT NULL
                           ORDER BY minute_start DESC LIMIT 1"""
                    ),
                    {"provider": provider_id, "instrument": instrument_id, "as_of": as_of},
                )
            ).one_or_none()
        return (row.minute_start, row.best_bid, row.best_ask) if row else None

    async def latest_open_interest_minute(
        self, provider_id: int, instrument_id: int
    ) -> datetime | None:
        async with self._engine.connect() as connection:
            result = await connection.execute(
                text(
                    """SELECT max(minute_start) FROM market_snapshots
                       WHERE provider_id = :provider AND instrument_id = :instrument
                         AND open_interest IS NOT NULL"""
                ),
                {"provider": provider_id, "instrument": instrument_id},
            )
            value: datetime | None = result.scalar_one()
        return value

    async def spread_minutes(
        self, provider_id: int, instrument_id: int, start: datetime, end: datetime
    ) -> int:
        """Minutes in [start, end) that have a recorded spread."""
        async with self._engine.connect() as connection:
            result = await connection.execute(
                text(
                    """SELECT count(*) FROM market_snapshots
                       WHERE provider_id = :provider AND instrument_id = :instrument
                         AND minute_start >= :start AND minute_start < :end
                         AND sample_count > 0"""
                ),
                {"provider": provider_id, "instrument": instrument_id, "start": start, "end": end},
            )
            return int(result.scalar_one())


class MarketRepository:
    """Funding and liquidation samples."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def latest_funding_time(self, provider_id: int, instrument_id: int) -> datetime | None:
        async with self._engine.connect() as connection:
            result = await connection.execute(
                text(
                    """SELECT max(funding_time) FROM funding_rates
                       WHERE provider_id = :provider AND instrument_id = :instrument"""
                ),
                {"provider": provider_id, "instrument": instrument_id},
            )
            value: datetime | None = result.scalar_one()
        return value

    async def funding_between(
        self, provider_id: int, instrument_id: int, start: datetime, end: datetime
    ) -> list[tuple[datetime, Decimal, Decimal | None]]:
        async with self._engine.connect() as connection:
            rows = await connection.execute(
                text(
                    """SELECT funding_time, funding_rate, mark_price FROM funding_rates
                       WHERE provider_id = :provider AND instrument_id = :instrument
                         AND funding_time >= :start AND funding_time < :end
                       ORDER BY funding_time"""
                ),
                {"provider": provider_id, "instrument": instrument_id, "start": start, "end": end},
            )
            return [(r.funding_time, r.funding_rate, r.mark_price) for r in rows]

    async def insert_funding(self, rows: Sequence[FundingRate]) -> None:
        if not rows:
            return
        values = [{**row.model_dump(), "data_origin": row.data_origin.value} for row in rows]
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    """INSERT INTO funding_rates (provider_id, instrument_id, funding_time,
                         funding_rate, mark_price, data_origin, received_at)
                       VALUES (:provider_id, :instrument_id, :funding_time, :funding_rate,
                         :mark_price, CAST(:data_origin AS data_origin_t), :received_at)
                       ON CONFLICT (provider_id, instrument_id, funding_time) DO NOTHING"""
                ),
                values,
            )

    async def insert_liquidation(self, sample: LiquidationSample) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    """INSERT INTO liquidation_samples (provider_id, instrument_id, event_time,
                         side, price, quantity, received_at)
                       VALUES (:provider_id, :instrument_id, :event_time, :side, :price,
                         :quantity, :received_at)
                       ON CONFLICT (provider_id, instrument_id, event_time, side, price, quantity)
                       DO NOTHING"""
                ),
                sample.model_dump(),
            )


class EventRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def downtime(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        """Downtime periods recorded inside [start, end), oldest first."""
        async with self._engine.connect() as connection:
            result = await connection.execute(
                text(
                    """SELECT message, data FROM system_events
                       WHERE event_type = 'downtime' AND occurred_at >= :start
                         AND occurred_at < :end
                       ORDER BY occurred_at"""
                ),
                {"start": start, "end": end},
            )
            return [{"reason": row.message, **row.data} for row in result]

    async def record(
        self,
        severity: Severity,
        component: str,
        event_type: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    """INSERT INTO system_events (severity, component, event_type, message, data)
                       VALUES (:severity, :component, :event_type, :message,
                         CAST(:data AS jsonb))"""
                ),
                {
                    "severity": severity,
                    "component": component,
                    "event_type": event_type,
                    "message": message,
                    "data": json.dumps(data or {}),
                },
            )
