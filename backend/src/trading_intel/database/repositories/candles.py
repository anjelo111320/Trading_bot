"""Closed candles. Forming candles have no path into this table."""

import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import RowMapping, text
from sqlalchemy.ext.asyncio import AsyncEngine

from trading_intel.domain.base import DataOrigin
from trading_intel.domain.candles import ClosedCandle, Timeframe

_INSERT = text(
    """
    INSERT INTO market_candles (
      provider_id, instrument_id, timeframe, open_time, close_time, open, high, low, close,
      volume, quote_volume, taker_buy_base_volume, taker_buy_quote_volume, trade_count,
      first_trade_id, last_trade_id, provider_open_time_raw, data_origin, received_at,
      ingest_run_id
    ) VALUES (
      :provider_id, :instrument_id, CAST(:timeframe AS timeframe_t), :open_time, :close_time,
      :open, :high, :low, :close, :volume, :quote_volume, :taker_buy_base_volume,
      :taker_buy_quote_volume, :trade_count, :first_trade_id, :last_trade_id,
      :provider_open_time_raw, CAST(:data_origin AS data_origin_t), :received_at, :ingest_run_id
    )
    ON CONFLICT (provider_id, instrument_id, timeframe, open_time) DO NOTHING
    """
)

_COLUMNS = """provider_id, instrument_id, timeframe::text AS timeframe, open_time, close_time,
    open, high, low, close, volume, quote_volume, taker_buy_base_volume,
    taker_buy_quote_volume, trade_count, first_trade_id, last_trade_id,
    provider_open_time_raw, data_origin::text AS data_origin, received_at"""

_COMPARED = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "quote_volume",
    "trade_count",
)


def _parameters(candle: ClosedCandle, run_id: UUID | None) -> dict[str, Any]:
    values = candle.model_dump()
    values["timeframe"] = candle.timeframe.value
    values["data_origin"] = candle.data_origin.value
    values["ingest_run_id"] = run_id
    return values


def _to_candle(row: RowMapping) -> ClosedCandle:
    return ClosedCandle(
        **{
            **row,
            "timeframe": Timeframe(row["timeframe"]),
            "data_origin": DataOrigin(row["data_origin"]),
        }
    )


def differences(stored: ClosedCandle, replacement: ClosedCandle) -> list[str]:
    """Fields that disagree. Numeric equality ignores trailing zeros."""
    return [name for name in _COMPARED if getattr(stored, name) != getattr(replacement, name)]


def _snapshot(candle: ClosedCandle) -> str:
    return json.dumps({name: str(getattr(candle, name)) for name in _COMPARED})


class CandleRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def insert(self, candles: Sequence[ClosedCandle], run_id: UUID | None = None) -> int:
        """Store candles once. Returns how many rows were new."""
        if not candles:
            return 0
        first, last = candles[0], candles[-1]
        key = {
            "provider_id": first.provider_id,
            "instrument_id": first.instrument_id,
            "timeframe": first.timeframe.value,
            "start": min(first.open_time, last.open_time),
            "end": max(first.open_time, last.open_time),
        }
        count_query = text(
            """SELECT count(*) FROM market_candles
               WHERE provider_id = :provider_id AND instrument_id = :instrument_id
                 AND timeframe = CAST(:timeframe AS timeframe_t)
                 AND open_time BETWEEN :start AND :end"""
        )
        async with self._engine.begin() as connection:
            before = (await connection.execute(count_query, key)).scalar_one()
            await connection.execute(_INSERT, [_parameters(c, run_id) for c in candles])
            after = (await connection.execute(count_query, key)).scalar_one()
        return int(after - before)

    async def replace_with_revision(
        self, stored: ClosedCandle, replacement: ClosedCandle, reason: str
    ) -> None:
        """Correct a stored candle, keeping an auditable record in one transaction."""
        key = {
            "provider_id": stored.provider_id,
            "instrument_id": stored.instrument_id,
            "timeframe": stored.timeframe.value,
            "open_time": stored.open_time,
        }
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    """INSERT INTO market_candle_revisions (provider_id, instrument_id, timeframe,
                         open_time, previous, replacement, reason)
                       VALUES (:provider_id, :instrument_id, CAST(:timeframe AS timeframe_t),
                         :open_time, CAST(:previous AS jsonb), CAST(:replacement AS jsonb),
                         :reason)"""
                ),
                {
                    **key,
                    "previous": _snapshot(stored),
                    "replacement": _snapshot(replacement),
                    "reason": reason,
                },
            )
            await connection.execute(
                text(
                    """UPDATE market_candles SET open = :open, high = :high, low = :low,
                         close = :close, volume = :volume, quote_volume = :quote_volume,
                         taker_buy_base_volume = :taker_buy_base_volume,
                         taker_buy_quote_volume = :taker_buy_quote_volume,
                         trade_count = :trade_count, first_trade_id = :first_trade_id,
                         last_trade_id = :last_trade_id, received_at = :received_at
                       WHERE provider_id = :provider_id AND instrument_id = :instrument_id
                         AND timeframe = CAST(:timeframe AS timeframe_t)
                         AND open_time = :open_time"""
                ),
                _parameters(replacement, None),
            )

    async def latest_open_time(
        self, provider_id: int, instrument_id: int, timeframe: Timeframe
    ) -> datetime | None:
        async with self._engine.connect() as connection:
            result = await connection.execute(
                text(
                    """SELECT max(open_time) FROM market_candles
                       WHERE provider_id = :provider AND instrument_id = :instrument
                         AND timeframe = CAST(:timeframe AS timeframe_t)"""
                ),
                {"provider": provider_id, "instrument": instrument_id, "timeframe": timeframe},
            )
            value: datetime | None = result.scalar_one()
        return value

    async def open_times(
        self,
        provider_id: int,
        instrument_id: int,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> list[datetime]:
        async with self._engine.connect() as connection:
            result = await connection.execute(
                text(
                    """SELECT open_time FROM market_candles
                       WHERE provider_id = :provider AND instrument_id = :instrument
                         AND timeframe = CAST(:timeframe AS timeframe_t)
                         AND open_time >= :start AND open_time < :end
                       ORDER BY open_time"""
                ),
                {
                    "provider": provider_id,
                    "instrument": instrument_id,
                    "timeframe": timeframe,
                    "start": start,
                    "end": end,
                },
            )
            return list(result.scalars().all())

    async def range(
        self,
        provider_id: int,
        instrument_id: int,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> list[ClosedCandle]:
        """Candles with an open time in [start, end), oldest first."""
        query = text(
            f"""SELECT {_COLUMNS} FROM market_candles
                WHERE provider_id = :provider AND instrument_id = :instrument
                  AND timeframe = CAST(:timeframe AS timeframe_t)
                  AND open_time >= :start AND open_time < :end
                ORDER BY open_time"""  # noqa: S608
        )
        params = {
            "provider": provider_id,
            "instrument": instrument_id,
            "timeframe": timeframe,
            "start": start,
            "end": end,
        }
        async with self._engine.connect() as connection:
            rows = (await connection.execute(query, params)).mappings().all()
        return [_to_candle(row) for row in rows]

    async def page(
        self,
        provider_id: int,
        instrument_id: int,
        timeframe: Timeframe,
        limit: int,
        before: datetime | None = None,
    ) -> list[ClosedCandle]:
        """The newest `limit` candles opening before `before`, returned oldest first."""
        query = text(
            f"""SELECT {_COLUMNS} FROM market_candles
                WHERE provider_id = :provider AND instrument_id = :instrument
                  AND timeframe = CAST(:timeframe AS timeframe_t)
                  AND (CAST(:before AS timestamptz) IS NULL OR open_time < :before)
                ORDER BY open_time DESC LIMIT :limit"""  # noqa: S608
        )
        params = {
            "provider": provider_id,
            "instrument": instrument_id,
            "timeframe": timeframe,
            "before": before,
            "limit": limit,
        }
        async with self._engine.connect() as connection:
            rows = (await connection.execute(query, params)).mappings().all()
        return [_to_candle(row) for row in reversed(rows)]

    async def count(self, provider_id: int, instrument_id: int, timeframe: Timeframe) -> int:
        async with self._engine.connect() as connection:
            result = await connection.execute(
                text(
                    """SELECT count(*) FROM market_candles
                       WHERE provider_id = :provider AND instrument_id = :instrument
                         AND timeframe = CAST(:timeframe AS timeframe_t)"""
                ),
                {"provider": provider_id, "instrument": instrument_id, "timeframe": timeframe},
            )
            return int(result.scalar_one())

    async def for_analysis(
        self,
        provider_id: int,
        instrument_id: int,
        timeframe: Timeframe,
        as_of: datetime,
        limit: int,
    ) -> list[ClosedCandle]:
        """Candles that had closed by `as_of`, excluding synthetic data."""
        query = text(
            f"""SELECT {_COLUMNS} FROM market_candles
                WHERE provider_id = :provider AND instrument_id = :instrument
                  AND timeframe = CAST(:timeframe AS timeframe_t)
                  AND close_time <= :as_of AND data_origin <> 'synthetic'
                ORDER BY open_time DESC LIMIT :limit"""  # noqa: S608
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
        return [_to_candle(row) for row in reversed(rows)]
