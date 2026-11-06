"""Simulated positions, fills and outcomes."""

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from trading_intel.domain.signals import EntryType, Side, SignalState
from trading_intel.paper_trading.simulator import Fill
from trading_intel.risk_management.models import AccountState

ZERO: Final = Decimal(0)


@dataclass(frozen=True)
class OpenTrade:
    position_id: UUID
    recommendation_id: UUID
    account_id: UUID
    provider_id: int
    instrument_id: int
    side: Side
    entry_type: EntryType
    entry: Decimal
    stop: Decimal
    targets: tuple[Decimal, ...]
    allocation: tuple[Decimal, ...]
    quantity: Decimal
    created_at: datetime
    expires_at: datetime
    state: SignalState
    inputs: dict[str, Any]
    strategy: str = ""  # The strategy configuration's name.
    # Tightened stops, each effective from the first candle after its time (D039).
    stop_moves: tuple[tuple[datetime, Decimal], ...] = ()


class PaperRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def open_position(
        self,
        account_id: UUID,
        recommendation_id: UUID,
        instrument_id: int,
        side: Side,
        quantity: Decimal,
    ) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    """INSERT INTO paper_positions (account_id, recommendation_id, instrument_id,
                         side, status, planned_quantity)
                       VALUES (:account, :recommendation, :instrument, CAST(:side AS side_t),
                         'pending_entry', :quantity)
                       ON CONFLICT (recommendation_id) DO NOTHING"""
                ),
                {
                    "account": account_id,
                    "recommendation": recommendation_id,
                    "instrument": instrument_id,
                    "side": side,
                    "quantity": quantity,
                },
            )

    async def active(self, provider_id: int, instrument_id: int) -> list[OpenTrade]:
        query = text(
            """SELECT p.id AS position_id, r.id AS recommendation_id, p.account_id, r.provider_id,
                      r.instrument_id, p.side::text AS side, r.entry_type::text AS entry_type,
                      r.entry_price, r.stop_loss, p.planned_quantity, r.created_at, r.expires_at,
                      s.state::text AS state, a.inputs, c.name AS strategy,
                      (SELECT array_agg(m.effective_after ORDER BY m.effective_after)
                       FROM paper_stop_moves m WHERE m.position_id = p.id) AS moved_at,
                      (SELECT array_agg(m.stop_price ORDER BY m.effective_after)
                       FROM paper_stop_moves m WHERE m.position_id = p.id) AS moved_to,
                      (SELECT array_agg(t.price ORDER BY t.target_no) FROM trade_targets t
                       WHERE t.recommendation_id = r.id) AS targets,
                      (SELECT array_agg(t.allocation_fraction ORDER BY t.target_no)
                       FROM trade_targets t WHERE t.recommendation_id = r.id) AS allocation
               FROM paper_positions p
               JOIN trade_recommendations r ON r.id = p.recommendation_id
               JOIN signal_current_state s ON s.recommendation_id = r.id
               JOIN risk_assessments a ON a.recommendation_id = r.id
               JOIN strategy_configurations c ON c.id = r.strategy_configuration_id
               WHERE p.status IN ('pending_entry', 'open') AND r.provider_id = :provider
                 AND r.instrument_id = :instrument"""
        )
        params = {"provider": provider_id, "instrument": instrument_id}
        async with self._engine.connect() as connection:
            rows = (await connection.execute(query, params)).mappings().all()
        return [
            OpenTrade(
                position_id=row["position_id"],
                recommendation_id=row["recommendation_id"],
                account_id=row["account_id"],
                provider_id=row["provider_id"],
                instrument_id=row["instrument_id"],
                side=Side(row["side"]),
                entry_type=EntryType(row["entry_type"]),
                entry=row["entry_price"],
                stop=row["stop_loss"],
                targets=tuple(row["targets"]),
                allocation=tuple(row["allocation"]),
                quantity=row["planned_quantity"],
                created_at=row["created_at"],
                expires_at=row["expires_at"],
                state=SignalState(row["state"]),
                inputs=row["inputs"],
                strategy=row["strategy"],
                stop_moves=tuple(zip(row["moved_at"] or (), row["moved_to"] or (), strict=True)),
            )
            for row in rows
        ]

    async def record_stop_move(
        self, position_id: UUID, after: datetime, stop: Decimal, reason: str
    ) -> bool:
        """A tighter stop from the first candle after `after`. False if already recorded."""
        async with self._engine.begin() as connection:
            result = await connection.execute(
                text(
                    """INSERT INTO paper_stop_moves (position_id, effective_after, stop_price,
                         reason)
                       VALUES (:position, :after, :stop, :reason)
                       ON CONFLICT (position_id, effective_after) DO NOTHING"""
                ),
                {"position": position_id, "after": after, "stop": stop, "reason": reason},
            )
        return result.rowcount == 1

    async def record_fill(
        self, position_id: UUID, fill: Fill, reconstructed: bool, market_event: dict[str, Any]
    ) -> bool:
        """The key stops a replay from filling twice. Returns False for a repeat."""
        key = f"{position_id}:{fill.kind}:{fill.at.isoformat()}"
        async with self._engine.begin() as connection:
            result = await connection.execute(
                text(
                    """INSERT INTO paper_executions (position_id, kind, quantity, fill_price, fee,
                         spread_cost, slippage_cost, funding, market_event, idempotency_key,
                         reconstructed, executed_at)
                       VALUES (:position, :kind, :quantity, :price, :fee, :spread, :slippage,
                         :funding, CAST(:event AS jsonb), :key, :reconstructed, :at)
                       ON CONFLICT (idempotency_key) DO NOTHING
                       RETURNING id"""
                ),
                {
                    "position": position_id,
                    "kind": fill.kind,
                    "quantity": fill.quantity,
                    "price": fill.price,
                    "fee": fill.fee,
                    "spread": fill.spread_cost,
                    "slippage": fill.slippage_cost,
                    "funding": fill.funding,
                    "event": json.dumps(market_event),
                    "key": key,
                    "reconstructed": reconstructed,
                    "at": fill.at,
                },
            )
            return result.first() is not None

    async def update_position(
        self,
        position_id: UUID,
        *,
        status: str,
        open_quantity: Decimal,
        average_entry: Decimal | None,
        realized_pnl: Decimal,
        costs_paid: Decimal,
        opened_at: datetime | None,
        closed_at: datetime | None,
    ) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    """UPDATE paper_positions SET status = :status, open_quantity = :open,
                         average_entry = :average, realized_pnl = :realized, costs_paid = :costs,
                         opened_at = :opened, closed_at = :closed, updated_at = now()
                       WHERE id = :id"""
                ),
                {
                    "id": position_id,
                    "status": status,
                    "open": open_quantity,
                    "average": average_entry,
                    "realized": realized_pnl,
                    "costs": costs_paid,
                    "opened": opened_at,
                    "closed": closed_at,
                },
            )

    async def move_signal(
        self,
        recommendation_id: UUID,
        previous: SignalState,
        state: SignalState,
        at: datetime,
        price: Decimal | None,
        cause: dict[str, Any],
    ) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    """INSERT INTO signal_events (recommendation_id, from_state, to_state,
                         market_price, occurred_at, cause)
                       VALUES (:id, CAST(:previous AS signal_state_t),
                         CAST(:state AS signal_state_t), :price, :at, CAST(:cause AS jsonb))"""
                ),
                {
                    "id": recommendation_id,
                    "previous": previous,
                    "state": state,
                    "price": price,
                    "at": at,
                    "cause": json.dumps(cause),
                },
            )
            await connection.execute(
                text(
                    """UPDATE signal_current_state SET state = CAST(:state AS signal_state_t),
                         updated_at = now() WHERE recommendation_id = :id"""
                ),
                {"id": recommendation_id, "state": state},
            )

    async def record_outcome(
        self,
        recommendation_id: UUID,
        outcome: str,
        gross: Decimal | None,
        costs: Decimal | None,
        net: Decimal | None,
        r_multiple: Decimal | None,
        at: datetime,
    ) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    """INSERT INTO trade_outcomes (recommendation_id, outcome, gross_pnl, costs,
                         net_pnl, r_multiple, resolved_at)
                       VALUES (:id, CAST(:outcome AS outcome_t), :gross, :costs, :net, :r, :at)
                       ON CONFLICT (recommendation_id) DO NOTHING"""
                ),
                {
                    "id": recommendation_id,
                    "outcome": outcome,
                    "gross": gross,
                    "costs": costs,
                    "net": net,
                    "r": r_multiple,
                    "at": at,
                },
            )

    async def account_state(
        self, account_id: UUID, starting_balance: Decimal, day_start: datetime
    ) -> AccountState:
        """Equity counts open positions at the latest recorded price, as the daily limit requires.

        The day's starting figure has only closed results, because the open value at midnight
        was not recorded, so an open loss carried over midnight counts as today's.
        """
        query = text(
            """SELECT COALESCE(sum(realized_pnl), 0) AS realized,
                      COALESCE(sum(realized_pnl) FILTER (
                        WHERE closed_at IS NOT NULL AND closed_at < :day_start), 0) AS before_today,
                      count(*) FILTER (WHERE status IN ('pending_entry', 'open')) AS open_count,
                      COALESCE(sum(open_quantity * average_entry) FILTER (
                        WHERE status = 'open'), 0) AS exposure
               FROM paper_positions WHERE account_id = :account"""
        )
        unrealized = text(
            """SELECT COALESCE(sum(
                 CASE WHEN p.side = 'LONG' THEN 1 ELSE -1 END
                 * (latest.mark - p.average_entry) * p.open_quantity), 0)
               FROM paper_positions p
               JOIN trade_recommendations r ON r.id = p.recommendation_id
               CROSS JOIN LATERAL (
                 SELECT (s.best_bid + s.best_ask) / 2 AS mark FROM market_snapshots s
                 WHERE s.provider_id = r.provider_id AND s.instrument_id = r.instrument_id
                   AND s.best_bid IS NOT NULL
                 ORDER BY s.minute_start DESC LIMIT 1
               ) latest
               WHERE p.account_id = :account AND p.status = 'open'"""
        )
        async with self._engine.connect() as connection:
            row = (
                await connection.execute(query, {"account": account_id, "day_start": day_start})
            ).one()
            open_pnl = (await connection.execute(unrealized, {"account": account_id})).scalar_one()
        return AccountState(
            equity=starting_balance + row.realized + open_pnl,
            day_start_equity=starting_balance + row.before_today,
            open_positions=int(row.open_count),
            gross_exposure=row.exposure,
        )

    async def positions(self, limit: int = 50) -> list[dict[str, Any]]:
        query = text(
            """SELECT p.id, p.instrument_id, i.canonical_symbol AS symbol, p.side::text AS side,
                      p.status, p.planned_quantity, p.open_quantity, p.average_entry,
                      p.realized_pnl, p.costs_paid, p.opened_at, p.closed_at,
                      r.stop_loss, s.state::text AS signal_state,
                      (SELECT bool_or(e.reconstructed) FROM paper_executions e
                       WHERE e.position_id = p.id) AS reconstructed
               FROM paper_positions p
               JOIN instruments i ON i.id = p.instrument_id
               JOIN trade_recommendations r ON r.id = p.recommendation_id
               LEFT JOIN signal_current_state s ON s.recommendation_id = r.id
               ORDER BY COALESCE(p.opened_at, p.updated_at) DESC LIMIT :limit"""
        )
        async with self._engine.connect() as connection:
            rows = (await connection.execute(query, {"limit": limit})).mappings().all()
        return [dict(row) for row in rows]

    async def performance(self) -> dict[str, Any]:
        query = text(
            """SELECT count(*) FILTER (WHERE counts_for_win_rate) AS resolved,
                      count(*) FILTER (WHERE outcome = 'WIN') AS wins,
                      count(*) FILTER (WHERE outcome = 'LOSS') AS losses,
                      count(*) FILTER (WHERE NOT counts_for_win_rate) AS unfilled,
                      COALESCE(sum(net_pnl), 0) AS net_pnl,
                      COALESCE(sum(costs), 0) AS costs,
                      avg(r_multiple) FILTER (WHERE counts_for_win_rate) AS expectancy_r
               FROM trade_outcomes"""
        )
        async with self._engine.connect() as connection:
            row = (await connection.execute(query)).mappings().one()
        return dict(row)
