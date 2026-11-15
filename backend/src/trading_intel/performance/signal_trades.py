"""What became of each signal's trade, for the Signals page and its chart links (D065).

A signal the risk engine approved becomes a trade: on Binance through the entry order the bot
sent for it, and on paper through the simulator's position. The trade's state, times, prices
and result come from Binance's own fills (D057) or the simulator's fills, never from the plan.
A rejected signal, and an approved one that sent nothing, has no trade. Pure: no I/O.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Final, Literal
from uuid import UUID

from trading_intel.performance.results import Trade

TradeState = Literal["waiting", "open", "won", "lost", "even", "not filled", "refused"]
# What the Signals page's result filter asks for.
ResultFilter = Literal["entered", "open", "won", "lost", "waiting", "not_entered"]
ENTERED: Final[frozenset[str]] = frozenset({"open", "won", "lost", "even"})


@dataclass(frozen=True)
class SignalTrade:
    state: TradeState
    opened_at: datetime | None = None  # The first entry fill.
    closed_at: datetime | None = None  # The fill that left the position flat.
    entry_price: Decimal | None = None  # Averaged over the entry fills.
    exit_price: Decimal | None = None  # Averaged over the exit fills.
    # USDT. Closed: the net result after fees and funding. Open on Binance: Binance's open
    # profit now, before exit fees. None while a paper trade is open.
    net: Decimal | None = None


def _closed(net: Decimal) -> TradeState:
    return "won" if net > 0 else "lost" if net < 0 else "even"


def _decimal(value: object) -> Decimal | None:
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return number if number.is_finite() and number != 0 else None


def exchange_trades(
    entries: Iterable[Mapping[str, Any]],
    trades: Iterable[Trade],
    unrealized: Mapping[str, Decimal],
    waiting: frozenset[str],
    now: datetime,
) -> dict[UUID, SignalTrade]:
    """Each signal's trade on a Binance account, from the entry the bot sent for it.

    `entries` are the account's entry rows, oldest first, each with Binance's reply, or with
    no reply when Binance refused it or never answered. `trades` are rebuilt from the stored
    fills, closed and open. `unrealized` is Binance's open profit on each coin the bot holds,
    and `waiting` the coins with a limit entry of the bot's in the book, both from the quant
    worker's last snapshot. A limit entry is waiting only while it is its coin's newest entry
    and its good-till time has not passed: an older one expired unfilled.
    """
    by_order = {trade.opening_order: trade for trade in trades}
    sent = [row for row in entries if "cancel" not in (row.get("request") or {})]
    newest = {str(row["symbol"]): row["recommendation_id"] for row in sent}
    now_ms = int(now.timestamp() * 1000)
    found: dict[UUID, SignalTrade] = {}
    for row in sent:
        key: UUID = row["recommendation_id"]
        reply: Mapping[str, Any] | None = row.get("response")
        if reply is None:
            found.setdefault(key, SignalTrade("refused"))
            continue
        symbol = str(row["symbol"])
        request: Mapping[str, Any] = row.get("request") or {}
        limit = request.get("type") == "LIMIT"
        order_id = reply.get("orderId")
        trade = by_order.get(int(order_id)) if order_id is not None else None
        if trade is not None and trade.closed_at is not None:
            found[key] = SignalTrade(
                _closed(trade.net),
                trade.opened_at,
                trade.closed_at,
                trade.entry_price,
                trade.exit_price,
                trade.net,
            )
        elif trade is not None:
            found[key] = SignalTrade(
                "open", trade.opened_at, None, trade.entry_price, None, unrealized.get(symbol)
            )
        elif not limit and _decimal(reply.get("executedQty")):
            # A market entry fills at once. Its fills are copied within a minute, so until
            # then the reply gives its price and the order's time stands for the fill's.
            found[key] = SignalTrade(
                "open",
                row["created_at"],
                None,
                _decimal(reply.get("avgPrice")),
                None,
                unrealized.get(symbol),
            )
        else:
            till = request.get("goodTillDate")
            live = till is None or int(till) > now_ms
            in_book = limit and live and symbol in waiting and newest.get(symbol) == key
            found[key] = SignalTrade("waiting" if in_book else "not filled")
    return found


def paper_trades(rows: Iterable[Mapping[str, Any]]) -> dict[UUID, SignalTrade]:
    """Each signal's trade in a paper account, from the simulator's position for it."""
    found: dict[UUID, SignalTrade] = {}
    for row in rows:
        status = row["status"]
        if status == "pending_entry":
            trade = SignalTrade("waiting")
        elif status == "cancelled":
            trade = SignalTrade("not filled")
        elif status == "open":
            trade = SignalTrade("open", row["opened_at"], None, row["average_entry"])
        else:
            net = Decimal(row["realized_pnl"])
            trade = SignalTrade(
                _closed(net),
                row["opened_at"],
                row["closed_at"],
                row["average_entry"],
                row["exit_price"],
                net,
            )
        found[row["recommendation_id"]] = trade
    return found


def wanted(trade: SignalTrade | None, result: ResultFilter) -> bool:
    """Whether a signal's trade matches the Signals page's result filter."""
    state = None if trade is None else trade.state
    if result == "entered":
        return state in ENTERED
    if result == "not_entered":
        return state not in ENTERED and state != "waiting"
    return state == result
