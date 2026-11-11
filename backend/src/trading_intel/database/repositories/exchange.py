"""Every request sent to Binance demo trading and its reply, and each day's starting equity (D048).

These tables are append-only, as is a reached loss stop (D053). A stop's price is kept with its
order, so a position that lost its stop can be given it back.
"""

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


class SentOrder(Protocol):
    """One request to Binance and its reply, as the trader records it. Storage needs no more,
    so the dashboard's API can read these tables without reaching the exchange code."""

    @property
    def symbol(self) -> str: ...
    @property
    def kind(self) -> str: ...
    @property
    def client_id(self) -> str: ...
    @property
    def request(self) -> dict[str, Any]: ...
    @property
    def response(self) -> dict[str, Any] | None: ...
    @property
    def error(self) -> str | None: ...


@dataclass(frozen=True)
class ExchangeTrade:
    """The trade behind a coin's Binance position: its latest filled entry."""

    key: str
    strategy: str
    recommendation_id: UUID


def _json(value: object) -> str:
    return json.dumps(value, default=str, sort_keys=True)


class ExchangeRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def record(
        self,
        account_id: UUID,
        recommendation_id: UUID | None,
        order: SentOrder,
        trade_key: str | None = None,
        stop_price: Decimal | None = None,
    ) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    """INSERT INTO exchange_orders (account_id, recommendation_id, symbol, kind,
                         client_id, trade_key, stop_price, request, response, error)
                       VALUES (:account, :recommendation, :symbol, :kind, :client, :key, :stop,
                               CAST(:request AS jsonb), CAST(:response AS jsonb), :error)"""
                ),
                {
                    "account": account_id,
                    "recommendation": recommendation_id,
                    "symbol": order.symbol,
                    "kind": order.kind,
                    "client": order.client_id,
                    "key": trade_key,
                    "stop": stop_price,
                    "request": _json(order.request),
                    "response": None if order.response is None else _json(order.response),
                    "error": order.error,
                },
            )

    async def stops(self, account_id: UUID) -> dict[str, tuple[Decimal, str]]:
        """Each coin's latest recorded stop price and its trade key."""
        async with self._engine.connect() as connection:
            rows = (
                await connection.execute(
                    text(
                        """SELECT DISTINCT ON (symbol) symbol, stop_price, trade_key
                           FROM exchange_orders
                           WHERE account_id = :account AND stop_price IS NOT NULL
                             AND trade_key IS NOT NULL
                           ORDER BY symbol, created_at DESC"""
                    ),
                    {"account": account_id},
                )
            ).all()
        return {row.symbol: (Decimal(row.stop_price), row.trade_key) for row in rows}

    async def latest_trade(self, account_id: UUID, symbol: str) -> ExchangeTrade | None:
        """The coin's latest entry Binance answered, and the strategy that sent it."""
        async with self._engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        """SELECT o.trade_key, c.name, o.recommendation_id
                           FROM exchange_orders o
                           JOIN trade_recommendations r ON r.id = o.recommendation_id
                           JOIN strategy_configurations c ON c.id = r.strategy_configuration_id
                           WHERE o.account_id = :account AND o.symbol = :symbol
                             AND o.kind = 'entry' AND o.response IS NOT NULL
                             AND o.trade_key IS NOT NULL
                           ORDER BY o.created_at DESC LIMIT 1"""
                    ),
                    {"account": account_id, "symbol": symbol},
                )
            ).one_or_none()
        if row is None:
            return None
        return ExchangeTrade(row.trade_key, row.name, row.recommendation_id)

    async def day_start(self, account_id: UUID, day: date, equity: Decimal) -> Decimal:
        """The equity first seen on a UTC day. Later calls that day return the same value."""
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    """INSERT INTO exchange_equity_days (account_id, day, equity)
                       VALUES (:account, :day, :equity) ON CONFLICT DO NOTHING"""
                ),
                {"account": account_id, "day": day, "equity": equity},
            )
            stored = (
                await connection.execute(
                    text(
                        "SELECT equity FROM exchange_equity_days "
                        "WHERE account_id = :account AND day = :day"
                    ),
                    {"account": account_id, "day": day},
                )
            ).scalar_one()
        return Decimal(stored)

    async def baseline(self, account_id: UUID) -> Decimal | None:
        """Binance's equity on the first day this account was recorded: where its budget began."""
        async with self._engine.connect() as connection:
            stored = (
                await connection.execute(
                    text(
                        "SELECT equity FROM exchange_equity_days WHERE account_id = :account "
                        "ORDER BY day LIMIT 1"
                    ),
                    {"account": account_id},
                )
            ).scalar_one_or_none()
        return None if stored is None else Decimal(stored)

    async def loss_stop(self, account_id: UUID, risk_profile_id: UUID) -> datetime | None:
        """When the account reached its loss stop under this profile version (D053), if it did."""
        async with self._engine.connect() as connection:
            return (
                await connection.execute(
                    text(
                        "SELECT reached_at FROM exchange_loss_stops "
                        "WHERE account_id = :account AND risk_profile_id = :profile"
                    ),
                    {"account": account_id, "profile": risk_profile_id},
                )
            ).scalar_one_or_none()

    async def record_loss_stop(
        self,
        account_id: UUID,
        risk_profile_id: UUID,
        reached_at: datetime,
        equity: Decimal,
        floor: Decimal,
    ) -> None:
        """Kept until the owner decides again, which takes a new profile version."""
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    """INSERT INTO exchange_loss_stops (account_id, risk_profile_id, equity,
                         floor, reached_at)
                       VALUES (:account, :profile, :equity, :floor, :reached)
                       ON CONFLICT DO NOTHING"""
                ),
                {
                    "account": account_id,
                    "profile": risk_profile_id,
                    "equity": equity,
                    "floor": floor,
                    "reached": reached_at,
                },
            )

    async def save_status(self, account_id: UUID, taken_at: datetime, body: dict[str, Any]) -> None:
        """Replace the account's snapshot. Only the latest is kept."""
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    """INSERT INTO exchange_status (account_id, taken_at, body)
                       VALUES (:account, :taken, CAST(:body AS jsonb))
                       ON CONFLICT (account_id)
                       DO UPDATE SET taken_at = EXCLUDED.taken_at, body = EXCLUDED.body"""
                ),
                {"account": account_id, "taken": taken_at, "body": _json(body)},
            )

    async def status(self, account_id: UUID) -> tuple[datetime, dict[str, Any]] | None:
        async with self._engine.connect() as connection:
            row = (
                await connection.execute(
                    text("SELECT taken_at, body FROM exchange_status WHERE account_id = :account"),
                    {"account": account_id},
                )
            ).one_or_none()
        return None if row is None else (row.taken_at, row.body)

    async def orders(self, account_id: UUID, limit: int = 50) -> list[dict[str, Any]]:
        """The latest requests sent to Binance, with what came back."""
        async with self._engine.connect() as connection:
            rows = (
                await connection.execute(
                    text(
                        """SELECT created_at, symbol, kind, request, response, error,
                                  recommendation_id
                           FROM exchange_orders WHERE account_id = :account
                           ORDER BY created_at DESC LIMIT :limit"""
                    ),
                    {"account": account_id, "limit": limit},
                )
            ).all()
        return [dict(row._mapping) for row in rows]

    async def recent(self, account_id: UUID, limit: int = 20) -> list[dict[str, Any]]:
        async with self._engine.connect() as connection:
            rows = (
                await connection.execute(
                    text(
                        """SELECT created_at, symbol, kind, client_id, error,
                                  response IS NOT NULL AS answered
                           FROM exchange_orders WHERE account_id = :account
                           ORDER BY created_at DESC LIMIT :limit"""
                    ),
                    {"account": account_id, "limit": limit},
                )
            ).all()
        return [dict(row._mapping) for row in rows]
