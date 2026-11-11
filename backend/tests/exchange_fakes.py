"""A fake Binance demo gateway for tests. It records calls and never reaches Binance."""

from decimal import Decimal
from typing import Any

from trading_intel.execution.binance_futures import AlgoType, OrderSide


class FakeGateway:
    """Records every call. Failures are set per call name: one exception for every call, or a
    list used in turn, where None lets that call through."""

    def __init__(
        self,
        positions: list[dict[str, Any]] | None = None,
        algo: list[dict[str, Any]] | None = None,
        entries: list[dict[str, Any]] | None = None,
        fails: dict[str, Exception | list[Exception | None]] | None = None,
        filled: str | None = "0.010",
        equity: str = "5000",
        available: str = "4800",
    ) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self._positions = positions or []
        self._algo = algo or []
        self._entries = entries or []  # Orders resting in the book, such as limit entries.
        self._fails = fails or {}
        self._filled = filled
        self._equity = equity
        self._available = available

    def _maybe_fail(self, name: str) -> None:
        failure = self._fails.get(name)
        if isinstance(failure, list):
            failure = failure.pop(0) if failure else None
        if failure is not None:
            raise failure

    async def account(self) -> dict[str, Any]:
        return {"totalMarginBalance": self._equity, "availableBalance": self._available}

    async def positions(self) -> list[dict[str, Any]]:
        return self._positions

    async def use_isolated(self, symbol: str) -> None:
        self.calls.append(("isolated", symbol))

    async def set_leverage(self, symbol: str, leverage: int) -> None:
        self.calls.append(("leverage", symbol, leverage))

    async def market_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        client_id: str,
        *,
        reduce_only: bool = False,
    ) -> dict[str, Any]:
        self.calls.append(("market", symbol, side, quantity, reduce_only))
        self._maybe_fail("close" if reduce_only else "entry")
        filled = str(quantity) if reduce_only or self._filled is None else self._filled
        return {"executedQty": filled, "avgPrice": "100.05"}

    async def limit_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        price: Decimal,
        client_id: str,
        good_till_ms: int,
    ) -> dict[str, Any]:
        self.calls.append(("limit", symbol, side, quantity, price, good_till_ms))
        self._maybe_fail("limit")
        return {"status": "NEW", "executedQty": "0", "avgPrice": "0"}

    async def open_entry_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        return [order for order in self._entries if symbol is None or order["symbol"] == symbol]

    async def cancel_order(self, symbol: str, client_id: str) -> dict[str, Any]:
        self.calls.append(("cancel entry", symbol, client_id))
        self._maybe_fail("cancel entry")
        self._entries = [o for o in self._entries if o.get("clientOrderId") != client_id]
        return {"status": "CANCELED"}

    async def algo_order(
        self,
        symbol: str,
        side: OrderSide,
        kind: AlgoType,
        trigger: Decimal,
        client_id: str,
        *,
        quantity: Decimal | None = None,
    ) -> dict[str, Any]:
        self.calls.append((kind, symbol, side, trigger, quantity))
        self._maybe_fail(kind)
        return {"algoId": len(self.calls)}

    async def open_algo_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        return [order for order in self._algo if symbol is None or order["symbol"] == symbol]

    async def cancel_algo_orders(self, symbol: str) -> None:
        self.calls.append(("cancel", symbol))

    async def cancel_algo_order(self, algo_id: int | str) -> dict[str, Any]:
        self.calls.append(("cancel one", algo_id))
        self._maybe_fail("cancel one")
        self._algo = [order for order in self._algo if order.get("algoId") != algo_id]
        return {"algoId": algo_id, "code": "200", "msg": "success"}
