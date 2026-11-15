"""What each order sent to Binance demo means in USDT, for the Bot page's orders table (D057).

Orders of one trade share its recommendation. The trade's entry price and size come from
Binance's own fills when they are stored, else from the entry's reply. A stop or target shows
what it would make or lose if it filled, before fees. The entry shows the trade's profit now:
Binance's unrealized profit while it is open, and its net result once closed.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Final, Literal

from trading_intel.performance.results import EntryOrder, Trade

ZERO: Final = Decimal(0)
TARGETS: Final = frozenset({"tp1", "tp2", "tp3"})

State = Literal["open", "won", "lost", "waiting", "not filled"]


@dataclass(frozen=True)
class OrderFigures:
    strategy: str | None = None
    value: Decimal | None = None  # Size at the order's price.
    if_hit: Decimal | None = None  # A stop's loss or a target's profit, before fees.
    now: Decimal | None = None  # The entry: profit now, or the closed trade's net.
    state: State | None = None
    risk: Decimal | None = None  # The entry: what the risk engine planned to lose at the stop.
    fill_price: Decimal | None = None  # The entry: the price it filled at, from Binance's fills.


@dataclass(frozen=True)
class _Entry:
    sign: int
    price: Decimal | None
    size: Decimal | None
    order_id: int | None
    limit: bool


def _decimal(value: object) -> Decimal | None:
    if value in (None, "", "0", "0.0", "0.00"):
        return None
    try:
        number = Decimal(str(value))
    except ArithmeticError:
        return None
    return number if number != 0 else None


def _entry(row: Mapping[str, Any], by_order: Mapping[int, Trade]) -> _Entry:
    request: Mapping[str, Any] = row.get("request") or {}
    response: Mapping[str, Any] = row.get("response") or {}
    order_id = int(response["orderId"]) if response.get("orderId") is not None else None
    limit = request.get("type") == "LIMIT"
    price = _decimal(response.get("avgPrice")) or (
        _decimal(request.get("price")) if limit else None
    )
    size = _decimal(response.get("executedQty")) or (
        _decimal(request.get("quantity")) if limit else None
    )
    trade = by_order.get(order_id) if order_id is not None else None
    if trade is not None:
        price, size = trade.entry_price or price, trade.size or size
    return _Entry(1 if request.get("side") == "BUY" else -1, price, size, order_id, limit)


def figure_orders(
    rows: Sequence[Mapping[str, Any]],
    closed: Sequence[Trade],
    still_open: Sequence[Trade],
    entries: Sequence[EntryOrder],
    unrealized: Mapping[str, Decimal],
    waiting: frozenset[str],
    now: datetime | None = None,
) -> list[OrderFigures]:
    """Figures for each row, in the rows' order.

    `unrealized` is Binance's unrealized profit per coin with a position, and `waiting` the
    coins with a limit entry of the bot's still in the book, both from the worker's last
    snapshot. A limit entry is waiting only while it is its coin's newest entry and, given
    `now`, before its good-till time, as on the Signals page (D065). Until 2026-11-15 an old
    expired entry showed as waiting whenever a newer one on its coin was.
    """
    trades = {t.opening_order: t for t in [*closed, *still_open]}
    plans = {entry.order_id: entry for entry in entries}
    by_trade: dict[Any, _Entry] = {}
    newest: dict[str, tuple[Any, Any]] = {}
    for row in rows:
        sent = row.get("request") or {}
        if row.get("kind") == "entry" and "cancel" not in sent and row.get("response"):
            by_trade[row.get("recommendation_id")] = _entry(row, trades)
            symbol, at = str(row.get("symbol")), row.get("created_at")
            if symbol not in newest or (at is not None and at > newest[symbol][0]):
                newest[symbol] = (at, row.get("recommendation_id"))
    current = {symbol: key for symbol, (_, key) in newest.items()}
    figures = []
    for row in rows:
        request: Mapping[str, Any] = row.get("request") or {}
        key = row.get("recommendation_id")
        entry = by_trade.get(key) if key is not None else None
        plan = plans.get(entry.order_id) if entry and entry.order_id is not None else None
        strategy = plan.strategy if plan else None
        if "cancel" in request or not row.get("response") or entry is None:
            figures.append(OrderFigures(strategy=strategy))
            continue
        kind = row.get("kind")
        if kind == "entry":
            in_book = _in_book(row, waiting, current, now)
            figures.append(_entry_figures(row, entry, plan, trades, unrealized, in_book))
            continue
        trigger = _decimal(request.get("triggerPrice"))
        size = _decimal(request.get("quantity")) or (entry.size if kind == "stop" else None)
        if trigger is None or size is None or entry.price is None or kind not in {"stop", *TARGETS}:
            figures.append(OrderFigures(strategy=strategy))
            continue
        figures.append(
            OrderFigures(
                strategy=strategy,
                value=size * trigger,
                if_hit=entry.sign * (trigger - entry.price) * size,
            )
        )
    return figures


def _in_book(
    row: Mapping[str, Any],
    waiting: frozenset[str],
    newest: Mapping[str, Any],
    now: datetime | None,
) -> bool:
    """A limit entry still resting on Binance: its coin's newest, before its good-till time."""
    symbol = str(row.get("symbol"))
    till = (row.get("request") or {}).get("goodTillDate")
    live = till is None or now is None or int(till) > int(now.timestamp() * 1000)
    return live and symbol in waiting and newest.get(symbol) == row.get("recommendation_id")


def _entry_figures(
    row: Mapping[str, Any],
    entry: _Entry,
    plan: EntryOrder | None,
    trades: Mapping[int, Trade],
    unrealized: Mapping[str, Decimal],
    in_book: bool,
) -> OrderFigures:
    symbol = str(row.get("symbol"))
    trade = trades.get(entry.order_id) if entry.order_id is not None else None
    value = entry.size * entry.price if entry.size and entry.price else None
    strategy = plan.strategy if plan else None
    risk = plan.planned_risk if plan else None
    now: Decimal | None = None
    state: State | None = None
    if trade is not None and trade.closed_at is not None:
        now, state = trade.net, "won" if trade.won else "lost"
    elif trade is not None or (not entry.limit and symbol in unrealized):
        now, state = unrealized.get(symbol), "open"
    elif entry.limit:
        state = "waiting" if in_book else "not filled"
    filled = entry.price if trade is not None or not entry.limit else None
    return OrderFigures(
        strategy=strategy, value=value, now=now, state=state, risk=risk, fill_price=filled
    )
