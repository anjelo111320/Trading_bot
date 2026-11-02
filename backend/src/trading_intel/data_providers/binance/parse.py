"""Turn Binance frames into domain types. Pure functions: same input, same output."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, NoReturn

from pydantic import ValidationError

from trading_intel.core.clock import from_epoch_ms
from trading_intel.domain.base import DataOrigin
from trading_intel.domain.candles import (
    EARLIEST_PLAUSIBLE_MS,
    LATEST_PLAUSIBLE_MS,
    ClosedCandle,
    FormingCandle,
    Timeframe,
)
from trading_intel.domain.instruments import InstrumentRules, InstrumentType
from trading_intel.domain.market import (
    FundingRate,
    LiquidationSample,
    MarkPrice,
    OpenInterest,
    TopOfBook,
)


class MalformedFrame(ValueError):
    """A frame that cannot be trusted. It is rejected and counted, never repaired."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class CandleContext:
    provider_id: int
    instrument_id: int
    timeframe: Timeframe
    origin: DataOrigin
    received_at: datetime


def _fail(reason: str, cause: Exception | None = None) -> NoReturn:
    raise MalformedFrame(reason) from cause


def number(value: object) -> Decimal:
    """Binance sends numbers as strings, so a bare float here means the format changed."""
    if not isinstance(value, str):
        _fail("number_not_a_string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        _fail("invalid_number", error)
    if not parsed.is_finite():
        _fail("non_finite_number")
    return parsed


def timestamp(value: object) -> datetime:
    """Reject values outside a plausible range, such as microseconds read as milliseconds."""
    if not isinstance(value, int) or isinstance(value, bool):
        _fail("timestamp_not_an_integer")
    if not EARLIEST_PLAUSIBLE_MS <= value <= LATEST_PLAUSIBLE_MS:
        _fail("implausible_timestamp")
    return from_epoch_ms(value)


def _build[T: (ClosedCandle, FormingCandle)](model: type[T], fields: dict[str, Any]) -> T:
    try:
        return model(**fields)
    except ValidationError as error:
        _fail(f"invalid_candle: {error.errors()[0]['msg']}", error)


def parse_rest_kline(
    row: Sequence[Any], context: CandleContext, server_time: datetime
) -> ClosedCandle | None:
    """Parse a REST row. Returns None for the forming candle that can end a response."""
    if len(row) < 11:
        _fail("kline_row_too_short")
    close_time = timestamp(row[6])
    if close_time >= server_time:
        return None
    return _build(
        ClosedCandle,
        {
            "provider_id": context.provider_id,
            "instrument_id": context.instrument_id,
            "timeframe": context.timeframe,
            "open_time": timestamp(row[0]),
            "close_time": close_time,
            "open": number(row[1]),
            "high": number(row[2]),
            "low": number(row[3]),
            "close": number(row[4]),
            "volume": number(row[5]),
            "quote_volume": number(row[7]),
            "trade_count": row[8],
            "taker_buy_base_volume": number(row[9]),
            "taker_buy_quote_volume": number(row[10]),
            "provider_open_time_raw": row[0],
            "data_origin": context.origin,
            "received_at": context.received_at,
        },
    )


def parse_stream_kline(
    data: Mapping[str, Any], context: CandleContext
) -> ClosedCandle | FormingCandle:
    """Only a frame with x=true is a closed candle."""
    try:
        kline = data["k"]
        fields: dict[str, Any] = {
            "provider_id": context.provider_id,
            "instrument_id": context.instrument_id,
            "timeframe": context.timeframe,
            "open_time": timestamp(kline["t"]),
            "close_time": timestamp(kline["T"]),
            "open": number(kline["o"]),
            "high": number(kline["h"]),
            "low": number(kline["l"]),
            "close": number(kline["c"]),
            "volume": number(kline["v"]),
            "quote_volume": number(kline["q"]),
            "trade_count": kline["n"],
            "taker_buy_base_volume": number(kline["V"]),
            "taker_buy_quote_volume": number(kline["Q"]),
            "first_trade_id": kline["f"],
            "last_trade_id": kline["L"],
            "provider_open_time_raw": kline["t"],
            "data_origin": context.origin,
            "received_at": context.received_at,
        }
        closed = kline["x"]
    except (KeyError, TypeError) as error:
        _fail("kline_field_missing", error)
    if closed is True:
        return _build(ClosedCandle, fields)
    if closed is False:
        return _build(FormingCandle, fields)
    _fail("kline_closed_flag_invalid")


def parse_book_ticker(
    data: Mapping[str, Any], provider_id: int, instrument_id: int, received_at: datetime
) -> TopOfBook:
    try:
        return TopOfBook(
            provider_id=provider_id,
            instrument_id=instrument_id,
            bid_price=number(data["b"]),
            bid_quantity=number(data["B"]),
            ask_price=number(data["a"]),
            ask_quantity=number(data["A"]),
            received_at=received_at,
        )
    except KeyError as error:
        _fail("book_ticker_field_missing", error)


def parse_mark_price(
    data: Mapping[str, Any], provider_id: int, instrument_id: int, received_at: datetime
) -> MarkPrice:
    try:
        return MarkPrice(
            provider_id=provider_id,
            instrument_id=instrument_id,
            mark_price=number(data["p"]),
            index_price=number(data["i"]),
            last_funding_rate=number(data["r"]),
            next_funding_time=timestamp(data["T"]),
            event_time=timestamp(data["E"]),
            received_at=received_at,
        )
    except KeyError as error:
        _fail("mark_price_field_missing", error)


def parse_force_order(
    data: Mapping[str, Any], provider_id: int, instrument_id: int, received_at: datetime
) -> LiquidationSample:
    try:
        order = data["o"]
        side = order["S"]
        if side not in ("BUY", "SELL"):
            _fail("force_order_side_invalid")
        return LiquidationSample(
            provider_id=provider_id,
            instrument_id=instrument_id,
            event_time=timestamp(order["T"]),
            side=side,
            price=number(order["ap"]),
            quantity=number(order["q"]),
            received_at=received_at,
        )
    except (KeyError, TypeError) as error:
        _fail("force_order_field_missing", error)


def parse_funding(
    row: Mapping[str, Any], provider_id: int, instrument_id: int, received_at: datetime
) -> FundingRate:
    try:
        mark = row.get("markPrice")
        return FundingRate(
            provider_id=provider_id,
            instrument_id=instrument_id,
            funding_time=timestamp(row["fundingTime"]),
            funding_rate=number(row["fundingRate"]),
            mark_price=number(mark) if mark else None,
            data_origin=DataOrigin.BACKFILL,
            received_at=received_at,
        )
    except KeyError as error:
        _fail("funding_field_missing", error)


def parse_open_interest(
    row: Mapping[str, Any], provider_id: int, instrument_id: int, received_at: datetime
) -> OpenInterest:
    try:
        return OpenInterest(
            provider_id=provider_id,
            instrument_id=instrument_id,
            open_interest=number(row["openInterest"]),
            event_time=timestamp(row["time"]),
            received_at=received_at,
        )
    except KeyError as error:
        _fail("open_interest_field_missing", error)


def parse_open_interest_history(
    row: Mapping[str, Any], provider_id: int, instrument_id: int, received_at: datetime
) -> OpenInterest:
    try:
        return OpenInterest(
            provider_id=provider_id,
            instrument_id=instrument_id,
            open_interest=number(row["sumOpenInterest"]),
            event_time=timestamp(row["timestamp"]),
            received_at=received_at,
        )
    except KeyError as error:
        _fail("open_interest_field_missing", error)


def parse_rules(symbol_info: Mapping[str, Any], instrument_type: InstrumentType) -> InstrumentRules:
    """Read exchange rules. Spot and USD-M name a few filters differently."""
    try:
        filters = {item["filterType"]: item for item in symbol_info["filters"]}
        price = filters["PRICE_FILTER"]
        lot = filters["LOT_SIZE"]
        market_lot = filters.get("MARKET_LOT_SIZE")
        if instrument_type is InstrumentType.SPOT:
            notional = filters["NOTIONAL"]
            minimum = number(notional["minNotional"])
            maximum = number(notional["maxNotional"])
        else:
            minimum = number(filters["MIN_NOTIONAL"]["notional"])
            maximum = None
        margin = symbol_info.get("maintMarginPercent")
        initial = symbol_info.get("requiredMarginPercent")
        return InstrumentRules(
            status=symbol_info.get("status") or symbol_info["contractStatus"],
            tick_size=number(price["tickSize"]),
            lot_step=number(lot["stepSize"]),
            min_qty=number(lot["minQty"]),
            max_qty=number(lot["maxQty"]),
            market_max_qty=number(market_lot["maxQty"]) if market_lot else None,
            min_notional=minimum,
            max_notional=maximum,
            initial_margin_fraction=number(initial) / 100 if initial else None,
            maintenance_margin_fraction=number(margin) / 100 if margin else None,
            raw=dict(symbol_info),
        )
    except (KeyError, TypeError) as error:
        _fail("rules_field_missing", error)
