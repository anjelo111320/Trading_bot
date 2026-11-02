"""Paper positions, driven by the stored 1M candles.

Each pass replays a trade from its start through the shared simulator, and idempotency keys
stop any fill from being recorded twice. The same pass therefore serves live running and
catching up after the computer slept. Fills from repaired candles are marked reconstructed.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Final

import structlog

from trading_intel.core.clock import Clock
from trading_intel.database.repositories.candles import CandleRepository
from trading_intel.database.repositories.operations import MarketRepository
from trading_intel.database.repositories.paper import OpenTrade, PaperRepository
from trading_intel.domain.base import DataOrigin
from trading_intel.domain.candles import ClosedCandle, Timeframe
from trading_intel.domain.signals import SignalState as S
from trading_intel.paper_trading.simulator import (
    Fill,
    OrderStatus,
    SimulatedOrder,
    TradeResult,
    TradeSimulator,
    summarise,
)
from trading_intel.trade_signals.lifecycle import advance

log = structlog.get_logger(__name__)

ZERO: Final = Decimal(0)
STATE_OF_FILL: Final = {
    "entry": S.ENTRY_TRIGGERED,
    "tp1": S.TP1_HIT,
    "tp2": S.TP2_HIT,
    "tp3": S.TP3_HIT,
    "stop": S.STOPPED,
    "expiry": S.EXPIRED,
    "invalidation": S.INVALIDATED,
}


def build_order(trade: OpenTrade) -> SimulatedOrder:
    costs = trade.inputs

    def number(name: str) -> Decimal:
        return Decimal(str(costs[name]))

    return SimulatedOrder(
        side=trade.side,
        entry_type=trade.entry_type,
        entry=trade.entry,
        stop=trade.stop,
        targets=trade.targets,
        allocation=trade.allocation,
        quantity=trade.quantity,
        tick=number("tick"),
        lot_step=number("lot_step"),
        taker_fee=number("taker_fee"),
        maker_fee=number("maker_fee"),
        half_spread=number("half_spread"),
        entry_slippage=number("entry_slippage"),
        stop_slippage=number("stop_slippage"),
        placed_at=trade.created_at,
        expires_at=trade.expires_at,
    )


@dataclass(frozen=True)
class SyncResult:
    positions: int
    new_fills: int


class PaperService:
    def __init__(
        self,
        candles: CandleRepository,
        market: MarketRepository,
        paper: PaperRepository,
        clock: Clock,
    ) -> None:
        self._candles = candles
        self._market = market
        self._paper = paper
        self._clock = clock

    async def sync(self, provider_id: int, instrument_id: int) -> SyncResult:
        trades = await self._paper.active(provider_id, instrument_id)
        new_fills = 0
        for trade in trades:
            new_fills += await self._sync_trade(trade)
        return SyncResult(len(trades), new_fills)

    async def _sync_trade(self, trade: OpenTrade) -> int:
        now = self._clock.now()
        start = Timeframe.M1.floor(trade.created_at)
        candles = await self._candles.range(
            trade.provider_id, trade.instrument_id, Timeframe.M1, start, now
        )
        funding = await self._market.funding_between(
            trade.provider_id, trade.instrument_id, trade.created_at, now
        )
        simulator = TradeSimulator(build_order(trade))
        pending = list(funding)
        added = 0
        state = trade.state
        for candle in candles:
            while pending and pending[0][0] < candle.close_time:
                at, rate, mark = pending.pop(0)
                for fill in simulator.on_funding(at, rate, mark or candle.close):
                    added += await self._store(trade, fill, candle)
            for fill in simulator.on_candle(candle):
                added += await self._store(trade, fill, candle)
                state = await self._move(trade, state, fill)
            if simulator.is_finished:
                break
        await self._save(trade, simulator)
        return added

    async def _store(self, trade: OpenTrade, fill: Fill, candle: ClosedCandle) -> int:
        reconstructed = candle.data_origin is not DataOrigin.LIVE
        event = {
            "candle_open": candle.open_time.isoformat(),
            "open": str(candle.open),
            "high": str(candle.high),
            "low": str(candle.low),
            "close": str(candle.close),
        }
        stored = await self._paper.record_fill(trade.position_id, fill, reconstructed, event)
        return 1 if stored else 0

    async def _move(self, trade: OpenTrade, state: S, fill: Fill) -> S:
        target = STATE_OF_FILL.get(fill.kind)
        if target is None or target == state:
            return state
        try:
            advance(state, target)
        except ValueError:
            return state  # Already recorded by an earlier pass over the same candles.
        await self._paper.move_signal(
            trade.recommendation_id, state, target, fill.at, fill.price, {"fill": fill.kind}
        )
        return target

    async def _save(self, trade: OpenTrade, simulator: TradeSimulator) -> None:
        result = summarise(trade.side, simulator.fills)
        status = {
            OrderStatus.PENDING: "pending_entry",
            OrderStatus.OPEN: "open",
            OrderStatus.CLOSED: "closed",
            OrderStatus.CANCELLED: "cancelled",
        }[simulator.status]
        await self._paper.update_position(
            trade.position_id,
            status=status,
            open_quantity=simulator.open_quantity,
            average_entry=result.entry_price,
            realized_pnl=result.net_pnl,
            costs_paid=result.fees,
            opened_at=result.entry_time,
            closed_at=result.exit_time if simulator.is_finished else None,
        )
        if simulator.is_finished:
            await self._record_outcome(trade, simulator, result)

    async def _record_outcome(
        self, trade: OpenTrade, simulator: TradeSimulator, result: TradeResult
    ) -> None:
        last_at: datetime = simulator.fills[-1].at
        if not result.entered:
            kind = "EXPIRED" if result.exit_reason == "expiry" else "INVALIDATED_BEFORE_ENTRY"
            await self._paper.record_outcome(
                trade.recommendation_id, kind, None, None, None, None, last_at
            )
            return
        risk = trade.quantity * abs(trade.entry - trade.stop)
        outcome = "WIN" if result.net_pnl > 0 else "LOSS" if result.net_pnl < 0 else "BREAKEVEN"
        await self._paper.record_outcome(
            trade.recommendation_id,
            outcome,
            result.gross_pnl,
            result.fees - result.funding,
            result.net_pnl,
            result.net_pnl / risk if risk else ZERO,
            last_at,
        )
