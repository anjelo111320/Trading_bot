"""Every request sent to Binance and its reply, and each day's starting equity (D048, D060).

These tables are append-only, as is a reached loss stop (D053). A stop's price is kept with its
order, so a position that lost its stop can be given it back. The real account also keeps when
each trade ended, the owner's closes from the dashboard, its arming, and the owner's transfers.
"""

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from trading_intel.performance.results import EntryOrder, Fill, Funding


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
    # The signal's planned entry and first stop, whose distance is the trade's R (D066).
    planned_entry: Decimal | None = None
    planned_stop: Decimal | None = None


@dataclass(frozen=True)
class CloseRequest:
    """The owner's close of one of the bot's trades, asked from the dashboard (D060)."""

    id: UUID
    symbol: str
    requested_by: str
    requested_at: datetime
    done_at: datetime | None = None
    outcome: str | None = None
    detail: str | None = None


CLOSE_COLUMNS = "id, symbol, requested_by, requested_at, done_at, outcome, detail"


def _close(row: Any) -> CloseRequest:
    return CloseRequest(
        row.id,
        row.symbol,
        row.requested_by,
        row.requested_at,
        row.done_at,
        row.outcome,
        row.detail,
    )


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

    async def first_stops(self, account_id: UUID) -> dict[str, Decimal]:
        """Each trade's first recorded stop, by trade key: the stop the risk engine approved,
        before any trail or profit lock moved it (D067)."""
        async with self._engine.connect() as connection:
            rows = (
                await connection.execute(
                    text(
                        """SELECT DISTINCT ON (trade_key) trade_key, stop_price
                           FROM exchange_orders
                           WHERE account_id = :account AND stop_price IS NOT NULL
                             AND trade_key IS NOT NULL
                           ORDER BY trade_key, created_at, id"""
                    ),
                    {"account": account_id},
                )
            ).all()
        return {row.trade_key: Decimal(row.stop_price) for row in rows}

    async def open_trades(self, account_id: UUID) -> dict[str, tuple[Decimal, str]]:
        """The bot's trades not yet seen to end, by coin: each one's stop price and trade key.

        On the real account these are the bot's positions. A position on any other coin is the
        owner's own (D060).
        """
        async with self._engine.connect() as connection:
            rows = (
                await connection.execute(
                    text(
                        """SELECT latest.symbol, latest.stop_price, latest.trade_key FROM (
                             SELECT DISTINCT ON (symbol) symbol, stop_price, trade_key
                             FROM exchange_orders
                             WHERE account_id = :account AND stop_price IS NOT NULL
                               AND trade_key IS NOT NULL
                             ORDER BY symbol, created_at DESC
                           ) latest
                           WHERE NOT EXISTS (
                             SELECT 1 FROM exchange_trade_ends e
                             WHERE e.account_id = :account AND e.trade_key = latest.trade_key
                           )"""
                    ),
                    {"account": account_id},
                )
            ).all()
        return {row.symbol: (Decimal(row.stop_price), row.trade_key) for row in rows}

    async def end_trade(self, account_id: UUID, trade_key: str, symbol: str, how: str) -> bool:
        """Record that a trade ended, once. Returns whether this call recorded it."""
        async with self._engine.begin() as connection:
            result = await connection.execute(
                text(
                    """INSERT INTO exchange_trade_ends (account_id, trade_key, symbol, how)
                       VALUES (:account, :key, :symbol, :how)
                       ON CONFLICT DO NOTHING RETURNING 1"""
                ),
                {"account": account_id, "key": trade_key, "symbol": symbol, "how": how},
            )
            return result.scalar_one_or_none() is not None

    async def request_close(self, account_id: UUID, symbol: str, email: str) -> CloseRequest:
        """Ask the quant worker to close the bot's trade on a coin. A close already waiting for
        the coin is returned instead of a second one."""
        async with self._engine.begin() as connection:
            row = (
                await connection.execute(
                    text(
                        f"""INSERT INTO exchange_close_requests (account_id, symbol, requested_by)
                            VALUES (:account, :symbol, :email)
                            ON CONFLICT (account_id, symbol) WHERE done_at IS NULL DO NOTHING
                            RETURNING {CLOSE_COLUMNS}"""  # noqa: S608
                    ),
                    {"account": account_id, "symbol": symbol, "email": email},
                )
            ).one_or_none()
            if row is None:
                row = (
                    await connection.execute(
                        text(
                            f"""SELECT {CLOSE_COLUMNS} FROM exchange_close_requests
                                WHERE account_id = :account AND symbol = :symbol
                                  AND done_at IS NULL"""  # noqa: S608
                        ),
                        {"account": account_id, "symbol": symbol},
                    )
                ).one()
        return _close(row)

    async def waiting_closes(self, account_id: UUID) -> list[CloseRequest]:
        async with self._engine.connect() as connection:
            rows = (
                await connection.execute(
                    text(
                        f"""SELECT {CLOSE_COLUMNS} FROM exchange_close_requests
                            WHERE account_id = :account AND done_at IS NULL
                            ORDER BY requested_at"""  # noqa: S608
                    ),
                    {"account": account_id},
                )
            ).all()
        return [_close(row) for row in rows]

    async def finish_close(self, request_id: UUID, outcome: str, detail: str | None) -> None:
        """Written once: a finished request cannot be changed (migration 0021)."""
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    """UPDATE exchange_close_requests
                       SET done_at = now(), outcome = :outcome, detail = :detail
                       WHERE id = :id AND done_at IS NULL"""
                ),
                {"id": request_id, "outcome": outcome, "detail": detail},
            )

    async def closes(self, account_id: UUID, limit: int = 10) -> list[CloseRequest]:
        """The latest closes asked from the dashboard, newest first."""
        async with self._engine.connect() as connection:
            rows = (
                await connection.execute(
                    text(
                        f"""SELECT {CLOSE_COLUMNS} FROM exchange_close_requests
                            WHERE account_id = :account
                            ORDER BY requested_at DESC LIMIT :limit"""  # noqa: S608
                    ),
                    {"account": account_id, "limit": limit},
                )
            ).all()
        return [_close(row) for row in rows]

    async def arming(
        self, account_id: UUID, default: bool = False
    ) -> tuple[bool, datetime | None, str | None]:
        """Whether the account may open trades, since when and set by whom. Until the owner
        sets it, `default`: off for the real account (D060), on for demo trading (D064)."""
        async with self._engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        """SELECT armed, created_at, changed_by FROM exchange_arming
                           WHERE account_id = :account ORDER BY created_at DESC LIMIT 1"""
                    ),
                    {"account": account_id},
                )
            ).one_or_none()
        return (default, None, None) if row is None else (row.armed, row.created_at, row.changed_by)

    async def set_armed(
        self, account_id: UUID, armed: bool, changed_by: str, note: str | None = None
    ) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    """INSERT INTO exchange_arming (account_id, armed, changed_by, note)
                       VALUES (:account, :armed, :by, :note)"""
                ),
                {"account": account_id, "armed": armed, "by": changed_by, "note": note},
            )

    async def last_transfer_at(self, account_id: UUID) -> datetime | None:
        async with self._engine.connect() as connection:
            return (
                await connection.execute(
                    text(
                        "SELECT max(moved_at) FROM exchange_transfers WHERE account_id = :account"
                    ),
                    {"account": account_id},
                )
            ).scalar_one_or_none()

    async def store_transfers(self, account_id: UUID, rows: list[dict[str, Any]]) -> int:
        """Binance's transfer income rows, once each. Returns how many were new."""
        stored = 0
        async with self._engine.begin() as connection:
            for row in rows:
                result = await connection.execute(
                    text(
                        """INSERT INTO exchange_transfers (account_id, tran_id, amount, asset,
                             moved_at)
                           VALUES (:account, :tran, :amount, :asset, :at)
                           ON CONFLICT DO NOTHING RETURNING 1"""
                    ),
                    {
                        "account": account_id,
                        "tran": int(row["tranId"]),
                        "amount": Decimal(str(row["income"])),
                        "asset": row.get("asset") or "",
                        "at": datetime.fromtimestamp(int(row["time"]) / 1000, UTC),
                    },
                )
                stored += result.scalar_one_or_none() is not None
        return stored

    async def first_seen(self, account_id: UUID) -> datetime | None:
        """When the bot first recorded the account's equity: transfers before it are in it."""
        async with self._engine.connect() as connection:
            return (
                await connection.execute(
                    text(
                        "SELECT created_at FROM exchange_equity_days WHERE account_id = :account "
                        "ORDER BY day LIMIT 1"
                    ),
                    {"account": account_id},
                )
            ).scalar_one_or_none()

    async def funded(self, account_id: UUID) -> Decimal | None:
        """What the owner has put in: the futures wallet's equity when the bot first saw it,
        plus the USDT moved in since, less what was moved out (D060)."""
        async with self._engine.connect() as connection:
            stored = (
                await connection.execute(
                    text(
                        """SELECT d.equity + coalesce((
                             SELECT sum(t.amount) FROM exchange_transfers t
                             WHERE t.account_id = d.account_id AND t.asset = 'USDT'
                               AND t.moved_at > d.created_at), 0) AS funded
                           FROM exchange_equity_days d WHERE d.account_id = :account
                           ORDER BY d.day LIMIT 1"""
                    ),
                    {"account": account_id},
                )
            ).scalar_one_or_none()
        return None if stored is None else Decimal(stored)

    async def moved_today(self, account_id: UUID, day: date) -> Decimal:
        """USDT moved in (positive) or out since the day's starting equity was recorded."""
        async with self._engine.connect() as connection:
            stored = (
                await connection.execute(
                    text(
                        """SELECT coalesce(sum(t.amount), 0) FROM exchange_transfers t
                           JOIN exchange_equity_days d
                             ON d.account_id = t.account_id AND d.day = :day
                           WHERE t.account_id = :account AND t.asset = 'USDT'
                             AND t.moved_at > d.created_at"""
                    ),
                    {"account": account_id, "day": day},
                )
            ).scalar_one()
        return Decimal(stored)

    async def latest_trade(self, account_id: UUID, symbol: str) -> ExchangeTrade | None:
        """The coin's latest entry Binance answered, and the strategy that sent it."""
        async with self._engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        """SELECT o.trade_key, c.name, o.recommendation_id, r.entry_price,
                                  r.stop_loss
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
        return ExchangeTrade(
            row.trade_key,
            row.name,
            row.recommendation_id,
            Decimal(row.entry_price),
            Decimal(row.stop_loss),
        )

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

    async def traded_symbols(self, account_id: UUID) -> dict[str, datetime]:
        """Each coin the bot sent an entry for, with its first entry's time."""
        async with self._engine.connect() as connection:
            rows = (
                await connection.execute(
                    text(
                        """SELECT symbol, min(created_at) AS first FROM exchange_orders
                           WHERE account_id = :account AND kind = 'entry' GROUP BY symbol"""
                    ),
                    {"account": account_id},
                )
            ).all()
        return {row.symbol: row.first for row in rows}

    async def last_fill_ids(self, account_id: UUID) -> dict[str, int]:
        async with self._engine.connect() as connection:
            rows = (
                await connection.execute(
                    text(
                        "SELECT symbol, max(trade_id) AS last FROM exchange_fills "
                        "WHERE account_id = :account GROUP BY symbol"
                    ),
                    {"account": account_id},
                )
            ).all()
        return {row.symbol: int(row.last) for row in rows}

    async def store_fills(self, account_id: UUID, rows: list[dict[str, Any]]) -> int:
        """Binance's fills exactly as sent, once each. Returns how many were new."""
        stored = 0
        async with self._engine.begin() as connection:
            for row in rows:
                result = await connection.execute(
                    text(
                        """INSERT INTO exchange_fills (account_id, symbol, trade_id, order_id,
                             side, price, quantity, realized_pnl, commission, commission_asset,
                             maker, filled_at, raw)
                           VALUES (:account, :symbol, :trade, :order, :side, :price, :qty, :pnl,
                             :fee, :asset, :maker, :at, CAST(:raw AS jsonb))
                           ON CONFLICT DO NOTHING RETURNING 1"""
                    ),
                    {
                        "account": account_id,
                        "symbol": row["symbol"],
                        "trade": int(row["id"]),
                        "order": int(row["orderId"]),
                        "side": row["side"],
                        "price": Decimal(str(row["price"])),
                        "qty": Decimal(str(row["qty"])),
                        "pnl": Decimal(str(row["realizedPnl"])),
                        "fee": Decimal(str(row["commission"])),
                        "asset": row["commissionAsset"],
                        "maker": bool(row["maker"]),
                        "at": datetime.fromtimestamp(int(row["time"]) / 1000, UTC),
                        "raw": _json(row),
                    },
                )
                stored += result.scalar_one_or_none() is not None
        return stored

    async def last_funding_at(self, account_id: UUID) -> datetime | None:
        async with self._engine.connect() as connection:
            return (
                await connection.execute(
                    text("SELECT max(paid_at) FROM exchange_funding WHERE account_id = :account"),
                    {"account": account_id},
                )
            ).scalar_one_or_none()

    async def store_funding(self, account_id: UUID, rows: list[dict[str, Any]]) -> int:
        stored = 0
        async with self._engine.begin() as connection:
            for row in rows:
                result = await connection.execute(
                    text(
                        """INSERT INTO exchange_funding (account_id, tran_id, symbol, amount,
                             asset, paid_at)
                           VALUES (:account, :tran, :symbol, :amount, :asset, :at)
                           ON CONFLICT DO NOTHING RETURNING 1"""
                    ),
                    {
                        "account": account_id,
                        "tran": int(row["tranId"]),
                        "symbol": row.get("symbol") or "",
                        "amount": Decimal(str(row["income"])),
                        "asset": row.get("asset") or "",
                        "at": datetime.fromtimestamp(int(row["time"]) / 1000, UTC),
                    },
                )
                stored += result.scalar_one_or_none() is not None
        return stored

    async def history(self, account_id: UUID) -> tuple[list[Fill], list[Funding], list[EntryOrder]]:
        """Every stored fill and funding payment, and every entry the bot sent with its
        strategy and planned risk, for rebuilding completed trades."""
        async with self._engine.connect() as connection:
            fills = (
                await connection.execute(
                    text(
                        """SELECT symbol, trade_id, order_id, side, price, quantity, realized_pnl,
                                  commission, commission_asset, filled_at
                           FROM exchange_fills WHERE account_id = :account"""
                    ),
                    {"account": account_id},
                )
            ).all()
            funding = (
                await connection.execute(
                    text(
                        """SELECT symbol, amount, paid_at FROM exchange_funding
                           WHERE account_id = :account AND asset = 'USDT'"""
                    ),
                    {"account": account_id},
                )
            ).all()
            entries = (
                await connection.execute(
                    text(
                        """SELECT (o.response->>'orderId')::bigint AS order_id, c.name,
                                  a.max_account_risk
                           FROM exchange_orders o
                           JOIN trade_recommendations r ON r.id = o.recommendation_id
                           JOIN strategy_configurations c ON c.id = r.strategy_configuration_id
                           LEFT JOIN risk_assessments a ON a.recommendation_id = r.id
                           WHERE o.account_id = :account AND o.kind = 'entry'
                             AND o.response->>'orderId' IS NOT NULL"""
                    ),
                    {"account": account_id},
                )
            ).all()
        return (
            [
                Fill(
                    row.symbol,
                    int(row.trade_id),
                    int(row.order_id),
                    row.side,
                    Decimal(row.price),
                    Decimal(row.quantity),
                    Decimal(row.realized_pnl),
                    Decimal(row.commission),
                    row.commission_asset,
                    row.filled_at,
                )
                for row in fills
            ],
            [Funding(row.symbol, Decimal(row.amount), row.paid_at) for row in funding],
            [
                EntryOrder(
                    int(row.order_id),
                    row.name,
                    None if row.max_account_risk is None else Decimal(row.max_account_risk),
                )
                for row in entries
            ],
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

    async def entries(self, account_id: UUID) -> list[dict[str, Any]]:
        """Every entry the bot sent for a signal, oldest first, with what came back (D065)."""
        async with self._engine.connect() as connection:
            rows = (
                await connection.execute(
                    text(
                        """SELECT recommendation_id, symbol, request, response, error, created_at
                           FROM exchange_orders
                           WHERE account_id = :account AND kind = 'entry'
                             AND recommendation_id IS NOT NULL
                           ORDER BY created_at, id"""
                    ),
                    {"account": account_id},
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
