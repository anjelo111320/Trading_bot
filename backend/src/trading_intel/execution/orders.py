"""The orders for one approved trade, worked out before anything is sent (D048).

Every price and size comes from the risk engine's approved sizing. Nothing here invents one.
"""

import hashlib
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal
from typing import Final, Literal

from trading_intel.domain.signals import Side

PREFIX: Final = "ati"
OrderKind = Literal["entry", "stop", "tp1", "tp2", "tp3", "close"]


def client_id(key: str, kind: OrderKind) -> str:
    """A stable order ID from the signal's key, so a repeat is refused rather than doubled.

    Binance allows 36 characters from `[.A-Z:/a-z0-9_-]`.
    """
    digest = hashlib.sha256(key.encode()).hexdigest()[:24]
    return f"{PREFIX}-{digest}-{kind}"


def opening_side(side: Side) -> Literal["BUY", "SELL"]:
    return "BUY" if side is Side.LONG else "SELL"


def closing_side(side: Side) -> Literal["BUY", "SELL"]:
    return "SELL" if side is Side.LONG else "BUY"


def floor_to(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


def target_sizes(
    quantity: Decimal, allocation: tuple[Decimal, ...], lot_step: Decimal, min_qty: Decimal
) -> tuple[Decimal, ...]:
    """Each target's share of the filled size, rounded down to the lot step.

    The last target takes what rounding left, as in the paper simulator. A share too small to
    trade is added to the target after it, so every take-profit is a valid order.
    """
    sizes: list[Decimal] = []
    carried = Decimal(0)
    remaining = quantity
    for index, share in enumerate(allocation):
        last = index == len(allocation) - 1
        size = remaining if last else floor_to(quantity * share, lot_step) + carried
        if not last and size < min_qty:
            carried, size = size, Decimal(0)
        else:
            carried = Decimal(0)
        sizes.append(size)
        remaining -= size
    return tuple(sizes)


@dataclass(frozen=True)
class TargetOrder:
    kind: OrderKind
    trigger: Decimal
    quantity: Decimal
    client_id: str


@dataclass(frozen=True)
class TradePlan:
    """One trade on Binance: a market entry, a stop for the whole position, and targets."""

    key: str
    symbol: str
    side: Side
    leverage: int
    quantity: Decimal
    stop: Decimal
    targets: tuple[Decimal, ...]
    allocation: tuple[Decimal, ...]
    lot_step: Decimal
    min_qty: Decimal

    @property
    def entry_id(self) -> str:
        return client_id(self.key, "entry")

    @property
    def stop_id(self) -> str:
        return client_id(self.key, "stop")

    def target_orders(self, filled: Decimal) -> list[TargetOrder]:
        """Take-profits for what actually filled. A target with nothing left is not placed."""
        sizes = target_sizes(filled, self.allocation, self.lot_step, self.min_qty)
        kinds: tuple[OrderKind, ...] = ("tp1", "tp2", "tp3")
        return [
            TargetOrder(kind, price, size, client_id(self.key, kind))
            for kind, price, size in zip(kinds, self.targets, sizes, strict=False)
            if size > 0
        ]
