"""Opens approved trades on Binance, and keeps every open position protected.

Stops and targets are held by Binance, so a position stays protected while this computer
sleeps. A position that cannot get its stop is closed at once rather than left unprotected.
A limit entry waits on Binance with its stop and targets already placed, so it is protected
from the moment it fills (D054).

On the owner's real account (D060), the trader touches only what the bot itself placed: its
orders carry the bot's client ID prefix, and its positions are the coins of its open trades.
The owner's own positions and orders on the account are left alone. A stop the owner sets in
the Binance app on one of the bot's trades protects it: the bot keeps it and the trade (D066).
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Final, Literal, Protocol

import httpx
import structlog

from trading_intel.domain.signals import Side
from trading_intel.execution.binance_futures import AlgoType, BinanceError, OrderSide
from trading_intel.execution.orders import (
    PREFIX,
    OrderKind,
    TargetOrder,
    TradePlan,
    client_id,
    closing_side,
    opening_side,
)

log = structlog.get_logger(__name__)

ZERO: Final = Decimal(0)
HISTORY_PAGE: Final = 1000  # Binance's most fills or income rows per call.
WEEK_MS: Final = 7 * 24 * 3600 * 1000  # Binance's longest fill window.
STOP_TYPES: Final = frozenset({"STOP_MARKET", "STOP"})
# Binance refuses a whole-position stop while another stands on the same side.
STOP_EXISTS: Final = -4130


class Gateway(Protocol):
    """The calls the trader makes. `BinanceFuturesGateway` provides them."""

    async def account(self) -> dict[str, Any]: ...
    async def positions(self) -> list[dict[str, Any]]: ...
    async def use_isolated(self, symbol: str) -> None: ...
    async def set_leverage(self, symbol: str, leverage: int) -> None: ...
    async def market_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        client_id: str,
        *,
        reduce_only: bool = False,
    ) -> dict[str, Any]: ...
    async def algo_order(
        self,
        symbol: str,
        side: OrderSide,
        kind: AlgoType,
        trigger: Decimal,
        client_id: str,
        *,
        quantity: Decimal | None = None,
    ) -> dict[str, Any]: ...
    async def limit_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        price: Decimal,
        client_id: str,
        good_till_ms: int,
    ) -> dict[str, Any]: ...
    async def open_entry_orders(self, symbol: str | None = None) -> list[dict[str, Any]]: ...
    async def cancel_order(self, symbol: str, client_id: str) -> dict[str, Any]: ...
    async def user_trades(
        self,
        symbol: str,
        *,
        from_id: int | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> list[dict[str, Any]]: ...
    async def funding_income(self, start_ms: int, end_ms: int) -> list[dict[str, Any]]: ...
    async def transfer_income(self, start_ms: int, end_ms: int) -> list[dict[str, Any]]: ...
    async def open_algo_orders(self, symbol: str | None = None) -> list[dict[str, Any]]: ...
    async def cancel_algo_orders(self, symbol: str) -> None: ...
    async def cancel_algo_order(self, algo_id: int | str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class Position:
    symbol: str
    amount: Decimal  # Positive long, negative short.
    entry_price: Decimal
    notional: Decimal  # Absolute, at the mark price.
    margin: Decimal = ZERO  # What the position holds as initial margin.
    mark_price: Decimal = ZERO
    unrealized: Decimal = ZERO
    liquidation: Decimal = ZERO  # Zero when Binance reports none.

    @property
    def side(self) -> Side:
        return Side.LONG if self.amount > 0 else Side.SHORT


@dataclass(frozen=True)
class PendingEntry:
    """A limit entry resting on Binance, not yet filled, or only part filled."""

    symbol: str
    side: Side
    price: Decimal
    quantity: Decimal  # What is still to fill.
    client_id: str

    @property
    def notional(self) -> Decimal:
        return self.price * self.quantity

    @property
    def by_bot(self) -> bool:
        return self.client_id.startswith(f"{PREFIX}-")


@dataclass(frozen=True)
class ExchangeView:
    """The account as Binance reports it. This, not a paper ledger, is what the risk engine sees."""

    equity: Decimal  # Wallet balance plus unrealized profit.
    available: Decimal  # What Binance can still lend as margin.
    positions: Mapping[str, Position]
    pending: Mapping[str, PendingEntry] = field(default_factory=dict)
    order_margin: Decimal = ZERO  # What Binance holds for resting entries.


@dataclass(frozen=True)
class Budget:
    """The account as the bot may use it: a fixed capital plus its own profit and loss (D048).

    Binance's demo account holds far more test funds than the owner trades with. The bot sees
    `capital` plus whatever Binance's equity has gained or lost since `baseline`, the equity
    first recorded for this account, and never more margin than that leaves free.
    """

    equity: Decimal
    day_start_equity: Decimal
    available: Decimal

    @classmethod
    def of(
        cls, view: ExchangeView, capital: Decimal, baseline: Decimal, day_start: Decimal
    ) -> Budget:
        equity = capital + view.equity - baseline
        in_use = sum((p.margin for p in view.positions.values()), view.order_margin)
        return cls(
            equity=equity,
            day_start_equity=capital + day_start - baseline,
            available=min(view.available, max(equity - in_use, ZERO)),
        )

    @classmethod
    def wallet(cls, view: ExchangeView, day_start: Decimal, moved_today: Decimal) -> Budget:
        """The real account: the whole futures wallet is the bot's, as the owner funds it (D060).

        Money the owner moved in or out since the day began shifts the day's start by as much,
        so a transfer is never counted as the day's profit or loss.
        """
        return cls(
            equity=view.equity, day_start_equity=day_start + moved_today, available=view.available
        )


@dataclass(frozen=True)
class OrderRecord:
    """One request to Binance and what came back, stored exactly as sent and received."""

    symbol: str
    kind: OrderKind
    client_id: str
    request: dict[str, Any]
    response: dict[str, Any] | None
    error: str | None = None
    code: int | None = None  # Binance's own error number, when it refused.


@dataclass
class OpenResult:
    filled: Decimal = ZERO
    average_price: Decimal | None = None
    protected: bool = False
    waiting: bool = False  # A limit entry rests on Binance with its stop and targets.
    records: list[OrderRecord] = field(default_factory=list)


@dataclass
class StopMove:
    """What a stop move did. `held` is the stop Binance holds afterwards and its order ID, or
    None when no stop of the bot's or the owner's is known to stand."""

    moved: bool = False
    held: tuple[Decimal, str] | None = None
    records: list[OrderRecord] = field(default_factory=list)


@dataclass
class CloseResult:
    """What closing a trade from the dashboard did (D060)."""

    outcome: Literal["closed", "nothing_open", "failed"] = "nothing_open"
    detail: str | None = None
    records: list[OrderRecord] = field(default_factory=list)


def _decimal(value: object) -> Decimal:
    return Decimal(str(value)) if value not in (None, "") else ZERO


def _is_stop(order: Mapping[str, Any]) -> bool:
    return str(order.get("orderType", order.get("type"))) in STOP_TYPES


def by_bot(order: Mapping[str, Any]) -> bool:
    """An order the bot placed: its client ID carries the bot's prefix."""
    cid = order.get("clientAlgoId") or order.get("clientOrderId") or ""
    return str(cid).startswith(f"{PREFIX}-")


def _is_entry(order: Mapping[str, Any]) -> bool:
    """A resting limit entry. Reduce-only orders only ever close."""
    return str(order.get("type")) == "LIMIT" and not order.get("reduceOnly")


def _protects(order: Mapping[str, Any], position: Position) -> bool:
    """A stop that closes the whole position: Binance's close-position kind, or a reduce-only
    stop for at least the position's size."""
    if not _is_stop(order) or str(order.get("side")) != closing_side(position.side):
        return False
    whole = str(order.get("closePosition")).lower() == "true"
    return whole or _decimal(order.get("quantity")) >= abs(position.amount)


def held_stops(
    positions: Mapping[str, Position], orders: Collection[Mapping[str, Any]]
) -> dict[str, Decimal]:
    """Each position's stop as Binance holds it, the bot's or the owner's: the tightest that
    closes the whole position. A position with none is left out."""
    held: dict[str, Decimal] = {}
    for order in orders:
        position = positions.get(str(order.get("symbol")))
        price = _decimal(order.get("triggerPrice"))
        if position is None or price <= 0 or not _protects(order, position):
            continue
        tightest = held.get(position.symbol)
        if tightest is None or position.side.sign * (price - tightest) > 0:
            held[position.symbol] = price
    return held


def _stop_exists(records: Collection[OrderRecord]) -> bool:
    """Binance refused a stop because a whole-position stop already stands on that side."""
    return any(record.code == STOP_EXISTS for record in records)


def _pending(order: Mapping[str, Any]) -> PendingEntry:
    return PendingEntry(
        str(order["symbol"]),
        Side.LONG if order.get("side") == "BUY" else Side.SHORT,
        _decimal(order.get("price")),
        _decimal(order.get("origQty")) - _decimal(order.get("executedQty")),
        str(order.get("clientOrderId", "")),
    )


class FuturesTrader:
    def __init__(self, gateway: Gateway, *, own_only: bool = False) -> None:
        """`own_only` on the real account: the owner's own orders and positions are never
        touched. Demo trading has none, so there the bot keeps the whole account tidy."""
        self._gateway = gateway
        self.own_only = own_only

    def _mine(self, order: Mapping[str, Any]) -> bool:
        return not self.own_only or by_bot(order)

    def _owners_stop(
        self, orders: Collection[Mapping[str, Any]], position: Position
    ) -> Mapping[str, Any] | None:
        """On the real account, a stop the owner set in the Binance app that protects the whole
        of one of the bot's positions. The bot keeps it and never touches it (D066)."""
        if not self.own_only:
            return None
        return next(
            (
                order
                for order in orders
                if order.get("symbol") == position.symbol
                and not by_bot(order)
                and _protects(order, position)
            ),
            None,
        )

    async def view(self) -> ExchangeView:
        account = await self._gateway.account()
        positions: dict[str, Position] = {}
        order_margin = ZERO
        for row in await self._gateway.positions():
            order_margin += _decimal(row.get("openOrderInitialMargin"))
            amount = _decimal(row.get("positionAmt"))
            if amount != 0:
                symbol = str(row["symbol"])
                notional = abs(_decimal(row.get("notional")))
                margin = _decimal(row.get("initialMargin") or row.get("isolatedWallet"))
                positions[symbol] = Position(
                    symbol,
                    amount,
                    _decimal(row.get("entryPrice")),
                    notional,
                    margin or notional,
                    _decimal(row.get("markPrice")),
                    _decimal(row.get("unRealizedProfit")),
                    _decimal(row.get("liquidationPrice")),
                )
        entries = [o for o in await self._gateway.open_entry_orders() if _is_entry(o)]
        return ExchangeView(
            equity=_decimal(account.get("totalMarginBalance")),
            available=_decimal(account.get("availableBalance")),
            positions=positions,
            pending={str(o["symbol"]): _pending(o) for o in entries},
            order_margin=order_margin,
        )

    async def open_orders(self) -> list[dict[str, Any]]:
        """Stops and targets Binance holds, for every coin."""
        return await self._gateway.open_algo_orders()

    async def fills(
        self, symbol: str, after_id: int | None, start_ms: int, end_ms: int
    ) -> list[dict[str, Any]]:
        """Every fill on a coin after `after_id`, or in the window when no fill is stored yet.

        Binance gives at most 1,000 fills a call and a window of at most 7 days, so both are
        walked until nothing is left (D057).
        """
        found: list[dict[str, Any]] = []
        if after_id is not None:
            while True:
                page = await self._gateway.user_trades(symbol, from_id=after_id + 1)
                found += page
                if len(page) < HISTORY_PAGE:
                    return found
                after_id = max(int(row["id"]) for row in page)
        start = start_ms
        while start <= end_ms:
            end = min(start + WEEK_MS - 1, end_ms)
            page = await self._gateway.user_trades(symbol, start_ms=start, end_ms=end)
            found += page
            start = (
                max(int(row["time"]) for row in page) + 1 if len(page) >= HISTORY_PAGE else end + 1
            )
        return found

    async def funding(self, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
        """Funding paid or received on every coin in the window, all pages."""
        found: list[dict[str, Any]] = []
        while start_ms <= end_ms:
            page = await self._gateway.funding_income(start_ms, end_ms)
            found += page
            if len(page) < HISTORY_PAGE:
                break
            start_ms = max(int(row["time"]) for row in page) + 1
        return found

    async def transfers(self, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
        """Money moved into or out of the futures wallet in the window, all pages (D060)."""
        found: list[dict[str, Any]] = []
        while start_ms <= end_ms:
            page = await self._gateway.transfer_income(start_ms, end_ms)
            found += page
            if len(page) < HISTORY_PAGE:
                break
            start_ms = max(int(row["time"]) for row in page) + 1
        return found

    async def _record(
        self,
        records: list[OrderRecord],
        symbol: str,
        kind: OrderKind,
        cid: str,
        request: dict[str, Any],
        call: Any,
    ) -> dict[str, Any] | None:
        try:
            response: dict[str, Any] = await call
        except BinanceError as error:
            records.append(
                OrderRecord(symbol, kind, cid, request, None, error.message, error.binance_code)
            )
            log.error("exchange_order_failed", symbol=symbol, kind=kind, detail=error.message[:200])
            return None
        except httpx.HTTPError as error:
            # No reply: the order may or may not exist. Reconciliation finds out within a minute.
            records.append(
                OrderRecord(symbol, kind, cid, request, None, f"no reply: {type(error).__name__}")
            )
            log.error("exchange_order_no_reply", symbol=symbol, kind=kind)
            return None
        records.append(OrderRecord(symbol, kind, cid, request, response))
        return response

    async def open_trade(self, plan: TradePlan) -> OpenResult:
        """Isolated margin and leverage, a market entry, then the stop, then the targets."""
        result = OpenResult()
        records = result.records
        symbol = plan.symbol
        try:
            await self._gateway.use_isolated(symbol)
            await self._gateway.set_leverage(symbol, plan.leverage)
        except BinanceError as error:
            records.append(
                OrderRecord(
                    symbol, "entry", plan.entry_id, {"leverage": plan.leverage}, None, error.message
                )
            )
            return result  # Nothing was opened.
        if plan.limit is not None:
            return await self._open_limit(plan, result)
        side = opening_side(plan.side)
        sent: dict[str, Any] = {"side": side, "type": "MARKET", "quantity": str(plan.quantity)}
        call = self._gateway.market_order(symbol, side, plan.quantity, plan.entry_id)
        entry = await self._record(records, symbol, "entry", plan.entry_id, sent, call)
        if entry is None:
            return result
        result.filled = _decimal(entry.get("executedQty"))
        result.average_price = _decimal(entry.get("avgPrice")) or None
        if result.filled <= 0:
            return result
        close = closing_side(plan.side)
        if not await self._stop(records, symbol, close, plan.stop, plan.stop_id):
            await self._flatten(records, symbol, close, result.filled, client_id(plan.key, "close"))
            return result
        result.protected = True
        for target in plan.target_orders(result.filled):
            await self._target(records, symbol, close, target)
        return result

    async def _open_limit(self, plan: TradePlan, result: OpenResult) -> OpenResult:
        """A limit entry that waits on Binance, with its stop and targets placed with it.

        Binance takes a whole-position stop only while a position is open, so this stop is
        reduce-only for the full planned size: it closes whatever fills, from the first fill.
        If the stop is refused, the entry is cancelled, and anything already filled is closed.
        """
        assert plan.limit is not None and plan.good_till_ms is not None
        records, symbol = result.records, plan.symbol
        side, close = opening_side(plan.side), closing_side(plan.side)
        sent: dict[str, Any] = {
            "side": side,
            "type": "LIMIT",
            "price": str(plan.limit),
            "quantity": str(plan.quantity),
            "timeInForce": "GTD",
            "goodTillDate": plan.good_till_ms,
        }
        call = self._gateway.limit_order(
            symbol, side, plan.quantity, plan.limit, plan.entry_id, plan.good_till_ms
        )
        entry = await self._record(records, symbol, "entry", plan.entry_id, sent, call)
        if entry is None:
            return result
        result.filled = _decimal(entry.get("executedQty"))
        result.average_price = _decimal(entry.get("avgPrice")) or None
        if not await self._stop(records, symbol, close, plan.stop, plan.stop_id, plan.quantity):
            await self._cancel_entry(records, symbol, plan.entry_id)
            if result.filled > 0:
                await self._flatten(
                    records, symbol, close, result.filled, client_id(plan.key, "close")
                )
            return result
        result.protected = True
        result.waiting = True
        for target in plan.target_orders(plan.quantity):
            await self._target(records, symbol, close, target)
        return result

    async def _cancel_entry(self, records: list[OrderRecord], symbol: str, cid: str) -> None:
        request = {"cancel": "order", "origClientOrderId": cid}
        call = self._gateway.cancel_order(symbol, cid)
        await self._record(records, symbol, "entry", cid, request, call)

    async def _target(
        self, records: list[OrderRecord], symbol: str, close: OrderSide, target: TargetOrder
    ) -> None:
        sent = {
            "side": close,
            "type": "TAKE_PROFIT_MARKET",
            "triggerPrice": str(target.trigger),
            "quantity": str(target.quantity),
            "reduceOnly": True,
        }
        call = self._gateway.algo_order(
            symbol, close, "TAKE_PROFIT_MARKET", target.trigger, target.client_id,
            quantity=target.quantity,
        )  # fmt: skip
        await self._record(records, symbol, target.kind, target.client_id, sent, call)

    async def _stop(
        self,
        records: list[OrderRecord],
        symbol: str,
        side: OrderSide,
        price: Decimal,
        cid: str,
        quantity: Decimal | None = None,
    ) -> bool:
        """A mark-price stop that closes the whole position, whatever its size.

        With a quantity it is reduce-only for that size instead, for an entry still waiting.
        """
        request: dict[str, Any] = {
            "side": side,
            "type": "STOP_MARKET",
            "triggerPrice": str(price),
        }
        if quantity is None:
            request["closePosition"] = True
        else:
            request |= {"quantity": str(quantity), "reduceOnly": True}
        call = self._gateway.algo_order(symbol, side, "STOP_MARKET", price, cid, quantity=quantity)
        return await self._record(records, symbol, "stop", cid, request, call) is not None

    async def _flatten(
        self, records: list[OrderRecord], symbol: str, side: OrderSide, quantity: Decimal, cid: str
    ) -> None:
        log.error("exchange_unprotected_closed", symbol=symbol)
        request = {"side": side, "type": "MARKET", "quantity": str(quantity), "reduceOnly": True}
        call = self._gateway.market_order(symbol, side, quantity, cid, reduce_only=True)
        await self._record(records, symbol, "close", cid, request, call)

    async def move_stop(self, symbol: str, price: Decimal, key: str) -> StopMove:
        """Replace the position's stop with one at `price`, such as the daily trend's trail.

        Binance holds one whole-position stop per side, so the old stop is cancelled first
        and the new one placed straight after. If the new one is refused, the old price goes
        back. Only if no stop is left at all is the position closed, as at entry. `key` must
        be new for each move, because Binance refuses a repeated order ID.

        A trade the owner protects with a stop of their own keeps it, and nothing is sent. A
        refusal because a whole-position stop already stands closes nothing (D066).
        """
        result = StopMove()
        records = result.records
        position = (await self.view()).positions.get(symbol)
        if position is None:
            return result
        close = closing_side(position.side)
        orders = await self._gateway.open_algo_orders(symbol)
        old = [order for order in orders if _is_stop(order) and self._mine(order)]
        owners = self._owners_stop(orders, position)
        if not old and owners is not None:
            result.held = (_decimal(owners.get("triggerPrice")), str(owners.get("clientAlgoId")))
            return result
        for order in old:
            request = {"cancel": "algoOrder", "algoId": order.get("algoId")}
            cid = str(order.get("clientAlgoId") or "cancel")
            call = self._gateway.cancel_algo_order(order.get("algoId", ""))
            if await self._record(records, symbol, "stop", cid, request, call) is None:
                return result  # The old stop may still be there; the minute check finds out.
        new_id = client_id(key, "stop")
        if await self._stop(records, symbol, close, price, new_id):
            result.moved, result.held = True, (price, new_id)
            return result
        if old:
            back_id = client_id(f"{key}:back", "stop")
            previous = _decimal(old[0].get("triggerPrice"))
            if await self._stop(records, symbol, close, previous, back_id):
                result.held = (previous, back_id)
                return result
        # Both refused. A stop Binance still reports means the cancel did not take effect.
        remaining = [
            o for o in await self._gateway.open_algo_orders(symbol) if _is_stop(o) and self._mine(o)
        ]
        if remaining:
            first = remaining[0]
            result.held = (_decimal(first.get("triggerPrice")), str(first.get("clientAlgoId")))
            return result
        if _stop_exists(records):
            log.warning("exchange_stop_already_held", symbol=symbol)
            return result
        await self._flatten(records, symbol, close, abs(position.amount), client_id(key, "close"))
        return result

    async def _bot_orders(
        self, algo: Collection[dict[str, Any]] | None = None
    ) -> dict[str, list[dict[str, Any]]]:
        """Stops and targets by coin: on the real account, only those the bot placed. `algo` is
        every stop and target Binance holds, when already read."""
        orders: dict[str, list[dict[str, Any]]] = {}
        for order in await self._gateway.open_algo_orders() if algo is None else algo:
            if self._mine(order):
                orders.setdefault(str(order["symbol"]), []).append(order)
        return orders

    async def _cancel_orders(
        self, records: list[OrderRecord], symbol: str, orders: list[dict[str, Any]]
    ) -> None:
        """A coin's leftover stops and targets: all at once on demo trading, or one at a time,
        only the bot's own, on the real account."""
        if self.own_only:
            for order in orders:
                request = {"cancel": "algoOrder", "algoId": order.get("algoId")}
                cid = str(order.get("clientAlgoId") or "cancel")
                call = self._gateway.cancel_algo_order(order.get("algoId", ""))
                await self._record(records, symbol, "close", cid, request, call)
            return
        try:
            await self._gateway.cancel_algo_orders(symbol)
            records.append(
                OrderRecord(symbol, "close", "cancel-all", {"cancel": "algoOpenOrders"}, {})
            )
        except BinanceError as error:
            records.append(
                OrderRecord(
                    symbol, "close", "cancel-all", {"cancel": "algoOpenOrders"}, None, error.message
                )
            )

    async def reconcile(self, stops: Mapping[str, tuple[Decimal, str]]) -> list[OrderRecord]:
        """Run every minute. `stops` holds each symbol's recorded stop price and trade key.

        - A coin with no position and no waiting entry keeps no stop or target: they are
          cancelled.
        - A waiting entry without a stop is cancelled, so it can never fill unprotected.
        - A position without a stop gets its recorded stop back, or is closed if none is known.

        On the real account (`own_only`), `stops` holds only the bot's open trades. Only the
        bot's own orders count, and a position on a coin without an open trade of the bot's is
        the owner's: it is left alone, never given a stop and never closed (D060).

        A bot trade the owner protects with a stop of their own, set in the Binance app, keeps
        it and stays open. A stop Binance refuses because a whole-position stop already stands
        closes nothing either. Until 2026-11-14 both closed the trade at market, which closed the
        real SOL short after the owner changed its stop in the app (D066).
        """
        records: list[OrderRecord] = []
        view = await self.view()
        algo = await self._gateway.open_algo_orders()
        orders = await self._bot_orders(algo)
        pending = {s: e for s, e in view.pending.items() if not self.own_only or e.by_bot}
        positions = {s: p for s, p in view.positions.items() if not self.own_only or s in stops}
        for symbol, entry in sorted(pending.items()):
            if not any(_is_stop(o) for o in orders.get(symbol, [])):
                log.error("exchange_entry_without_stop", symbol=symbol)
                await self._cancel_entry(records, symbol, entry.client_id)
        for symbol in sorted(set(orders) - set(positions) - set(pending)):
            await self._cancel_orders(records, symbol, orders[symbol])
        for symbol, position in sorted(positions.items()):
            if any(_is_stop(o) for o in orders.get(symbol, [])):
                continue
            close = closing_side(position.side)
            known = stops.get(symbol)
            if known is None:
                cid = client_id(f"orphan:{symbol}", "close")
                await self._flatten(records, symbol, close, abs(position.amount), cid)
                continue
            if self._owners_stop(algo, position) is not None:
                continue
            price, key = known
            if await self._stop(records, symbol, close, price, client_id(f"{key}:restop", "stop")):
                continue
            if _stop_exists(records[-1:]):
                log.warning("exchange_stop_already_held", symbol=symbol)
                continue
            await self._flatten(
                records,
                symbol,
                close,
                abs(position.amount),
                client_id(f"{key}:restop", "close"),
            )
        return records

    async def flatten_all(self, trades: Collection[str] = ()) -> list[OrderRecord]:
        """The kill switch: cancel every stop and target, then close every position at market.

        On the real account only the bot's: its waiting entries are cancelled and the coins of
        its open trades, `trades`, are closed first, then its own stops and targets cancelled.
        The owner's own positions and orders stay as they are.
        """
        records: list[OrderRecord] = []
        view = await self.view()
        if self.own_only:
            for symbol, entry in sorted(view.pending.items()):
                if entry.by_bot:
                    await self._cancel_entry(records, symbol, entry.client_id)
            for symbol, position in sorted(view.positions.items()):
                if symbol in trades:
                    cid = client_id(f"kill:{symbol}", "close")
                    side = closing_side(position.side)
                    await self._flatten(records, symbol, side, abs(position.amount), cid)
            for symbol, orders in sorted((await self._bot_orders()).items()):
                await self._cancel_orders(records, symbol, orders)
            return records
        symbols = {str(o["symbol"]) for o in await self._gateway.open_algo_orders()} | set(
            view.positions
        )
        for symbol in sorted(symbols):
            try:
                await self._gateway.cancel_algo_orders(symbol)
            except BinanceError as error:
                records.append(
                    OrderRecord(
                        symbol,
                        "close",
                        "cancel-all",
                        {"cancel": "algoOpenOrders"},
                        None,
                        error.message,
                    )
                )
        for symbol, position in sorted(view.positions.items()):
            cid = client_id(f"kill:{symbol}", "close")
            await self._flatten(
                records, symbol, closing_side(position.side), abs(position.amount), cid
            )
        return records

    async def close_trade(self, symbol: str, key: str) -> CloseResult:
        """Close the bot's trade on a coin now, at the owner's request from the dashboard (D060).

        A waiting entry is cancelled first, so nothing more fills. The position is closed at
        market, reduce-only, and keeps its stop until that close is done. Then the bot's stop
        and targets left on the coin are cancelled. `key` must be new for each close, because
        Binance refuses a repeated order ID.
        """
        result = CloseResult()
        records = result.records
        view = await self.view()
        entry = view.pending.get(symbol)
        if entry is not None and (not self.own_only or entry.by_bot):
            await self._cancel_entry(records, symbol, entry.client_id)
            if records[-1].response is None:
                result.outcome = "failed"
                result.detail = f"the waiting entry was not cancelled: {records[-1].error}"
                return result
            result.outcome = "closed"
            view = await self.view()  # Part of it may have filled before the cancel.
        position = view.positions.get(symbol)
        if position is not None:
            side, quantity = closing_side(position.side), abs(position.amount)
            cid = client_id(f"{key}:close", "close")
            request = {
                "side": side,
                "type": "MARKET",
                "quantity": str(quantity),
                "reduceOnly": True,
            }
            call = self._gateway.market_order(symbol, side, quantity, cid, reduce_only=True)
            if await self._record(records, symbol, "close", cid, request, call) is None:
                # Not closed, so its stop and targets stay on Binance.
                result.outcome, result.detail = "failed", records[-1].error
                return result
            result.outcome = "closed"
        left = [o for o in await self._gateway.open_algo_orders(symbol) if self._mine(o)]
        if left:
            await self._cancel_orders(records, symbol, left)
        log.info("exchange_trade_closed", symbol=symbol, outcome=result.outcome)
        return result


def describe(
    view: ExchangeView,
    orders: list[dict[str, Any]],
    budget: Budget,
    capital: Decimal,
    trades: Collection[str] | None = None,
) -> dict[str, Any]:
    """The account as the dashboard shows it, in plain values. Prices stay as Binance sent them.

    On the real account, `trades` holds the coins of the bot's open trades: a position on any
    other coin, and an order without the bot's ID, is marked as the owner's own (D060).
    """

    def text(value: Decimal) -> str:
        return format(value.normalize(), "f")

    def bot_position(symbol: str) -> bool:
        return trades is None or symbol in trades

    def bot_order(order: Mapping[str, Any]) -> bool:
        return trades is None or by_bot(order)

    return {
        "binance": {"equity": text(view.equity), "available": text(view.available)},
        "budget": {
            "capital": text(capital),
            "equity": text(budget.equity),
            "day_start_equity": text(budget.day_start_equity),
            "available": text(budget.available),
        },
        "positions": [
            {
                "symbol": p.symbol,
                "side": p.side.value,
                "quantity": text(abs(p.amount)),
                "entry_price": text(p.entry_price),
                "mark_price": text(p.mark_price),
                "notional": text(p.notional),
                "margin": text(p.margin),
                "unrealized": text(p.unrealized),
                "liquidation": text(p.liquidation) if p.liquidation > 0 else None,
                "bot": bot_position(p.symbol),
            }
            for p in sorted(view.positions.values(), key=lambda p: p.symbol)
        ],
        "orders": [
            {
                "symbol": str(order["symbol"]),
                "type": str(order.get("orderType", order.get("type"))),
                "side": str(order.get("side")),
                "trigger": str(order.get("triggerPrice")),
                "quantity": None if order.get("closePosition") else str(order.get("quantity")),
                "close_position": bool(order.get("closePosition")),
                "bot": bot_order(order),
            }
            for order in sorted(orders, key=_order_key)
        ]
        + [
            {
                "symbol": entry.symbol,
                "type": "LIMIT",
                "side": "BUY" if entry.side is Side.LONG else "SELL",
                "trigger": text(entry.price),
                "quantity": text(entry.quantity),
                "close_position": False,
                "bot": trades is None or entry.by_bot,
            }
            for entry in sorted(view.pending.values(), key=lambda e: e.symbol)
        ],
    }


def _order_key(order: dict[str, Any]) -> tuple[str, int, Decimal]:
    """By coin, the stop first, then the targets by price."""
    kind = str(order.get("orderType", order.get("type")))
    return str(order["symbol"]), 0 if kind in STOP_TYPES else 1, _decimal(order.get("triggerPrice"))
