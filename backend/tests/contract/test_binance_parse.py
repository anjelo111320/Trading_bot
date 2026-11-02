"""Parsing against real frames recorded from Binance."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from trading_intel.core.clock import from_epoch_ms
from trading_intel.data_providers.binance import parse
from trading_intel.data_providers.binance.parse import CandleContext, MalformedFrame
from trading_intel.domain.base import DataOrigin
from trading_intel.domain.candles import ClosedCandle, FormingCandle, Timeframe
from trading_intel.domain.instruments import InstrumentType

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
NOW = datetime(2026, 11, 2, tzinfo=UTC)


def load(path: str) -> Any:
    return json.loads((FIXTURES / path).read_text())


def context(origin: DataOrigin = DataOrigin.BACKFILL) -> CandleContext:
    return CandleContext(1, 1, Timeframe.M1, origin, NOW)


def kline_frames(path: str) -> list[dict[str, Any]]:
    return [f["data"] for f in load(path) if "kline" in f["stream"]]


@pytest.mark.parametrize(
    "path", ["binance_spot/klines_btcusdt_1m.json", "binance_usdm/klines_btcusdt_1m.json"]
)
def test_rest_klines_parse_and_the_forming_row_is_dropped(path: str) -> None:
    rows = load(path)
    server_time = from_epoch_ms(rows[-1][6])  # The last row has not closed yet.
    parsed = [parse.parse_rest_kline(row, context(), server_time) for row in rows]
    assert parsed[-1] is None
    assert all(isinstance(candle, ClosedCandle) for candle in parsed[:-1])


def test_rest_kline_keeps_the_raw_provider_time_and_exact_decimals() -> None:
    row = load("binance_spot/klines_btcusdt_1m.json")[0]
    candle = parse.parse_rest_kline(row, context(), NOW + timedelta(days=1))
    assert candle is not None
    assert candle.provider_open_time_raw == row[0]
    assert candle.close == Decimal(row[4])
    assert candle.close_time.microsecond == 999_000


@pytest.mark.parametrize(
    "path", ["binance_spot/stream_frames.json", "binance_usdm/market_stream_frames.json"]
)
def test_only_a_frame_with_x_true_becomes_a_closed_candle(path: str) -> None:
    frames = kline_frames(path)
    events = [parse.parse_stream_kline(f, context(DataOrigin.LIVE)) for f in frames]
    assert any(isinstance(e, ClosedCandle) for e in events)
    for frame, event in zip(frames, events, strict=True):
        expected = ClosedCandle if frame["k"]["x"] else FormingCandle
        assert type(event) is expected


def test_non_boolean_closed_flag_is_rejected() -> None:
    frame = json.loads(json.dumps(kline_frames("binance_spot/stream_frames.json")[0]))
    frame["k"]["x"] = "true"
    with pytest.raises(MalformedFrame, match="kline_closed_flag_invalid"):
        parse.parse_stream_kline(frame, context())


def test_microsecond_timestamp_is_rejected() -> None:
    """Regression for R9: microseconds read as milliseconds would land in year 58000."""
    row = load("binance_spot/klines_btcusdt_1m.json")[0]
    row = [row[0] * 1000, *row[1:]]
    with pytest.raises(MalformedFrame, match="implausible_timestamp"):
        parse.parse_rest_kline(row, context(), NOW + timedelta(days=1))


def test_inconsistent_candle_is_rejected_with_a_reason() -> None:
    row = list(load("binance_spot/klines_btcusdt_1m.json")[0])
    row[2] = "1.0"  # High below open.
    with pytest.raises(MalformedFrame, match="high_below_body"):
        parse.parse_rest_kline(row, context(), NOW + timedelta(days=1))


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        (1.5, "number_not_a_string"),
        ("abc", "invalid_number"),
        ("NaN", "non_finite_number"),
        ("Infinity", "non_finite_number"),
    ],
)
def test_bad_numbers_are_rejected(value: object, reason: str) -> None:
    with pytest.raises(MalformedFrame, match=reason):
        parse.number(value)


def test_short_rest_row_is_rejected() -> None:
    with pytest.raises(MalformedFrame, match="kline_row_too_short"):
        parse.parse_rest_kline([1, 2], context(), NOW)


@pytest.mark.parametrize(
    ("path", "stream"),
    [
        ("binance_spot/stream_frames.json", "btcusdt@bookTicker"),
        ("binance_usdm/public_stream_frames.json", "btcusdt@bookTicker"),
    ],
)
def test_book_ticker_parses_from_both_venues(path: str, stream: str) -> None:
    frame = next(f for f in load(path) if f["stream"] == stream)
    book = parse.parse_book_ticker(frame["data"], 1, 1, NOW)
    assert book.ask_price >= book.bid_price
    assert book.spread == book.ask_price - book.bid_price


def test_crossed_book_is_detected() -> None:
    data = {"b": "101", "B": "1", "a": "100", "A": "1"}
    assert parse.parse_book_ticker(data, 1, 1, NOW).is_crossed


def test_mark_price_parses() -> None:
    frames = load("binance_usdm/market_stream_frames.json")
    frame = next(f for f in frames if "markPrice" in f["stream"])
    mark = parse.parse_mark_price(frame["data"], 1, 1, NOW)
    assert mark.mark_price == Decimal(frame["data"]["p"])
    assert mark.index_price == Decimal(frame["data"]["i"])


def test_funding_time_keeps_its_real_millisecond_offset() -> None:
    rows = load("binance_usdm/funding_rate.json")
    offset = next(r for r in rows if r["fundingTime"] % 1000)
    funding = parse.parse_funding(offset, 1, 1, NOW)
    assert funding.funding_time.microsecond == offset["fundingTime"] % 1000 * 1000
    assert funding.data_origin is DataOrigin.BACKFILL


def test_open_interest_parses_from_both_endpoints() -> None:
    current = parse.parse_open_interest(load("binance_usdm/open_interest.json"), 1, 1, NOW)
    history = load("binance_usdm/open_interest_hist.json")[0]
    assert current.open_interest > 0
    assert parse.parse_open_interest_history(history, 1, 1, NOW).open_interest > 0


def test_spot_rules_match_verified_values() -> None:
    info = load("binance_spot/exchange_info_btcusdt.json")["symbols"][0]
    rules = parse.parse_rules(info, InstrumentType.SPOT)
    assert rules.tick_size == Decimal("0.01")
    assert rules.lot_step == Decimal("0.00001")
    assert rules.min_notional == Decimal(5)
    assert rules.status == "TRADING"


def test_perpetual_rules_differ_from_spot() -> None:
    info = load("binance_usdm/exchange_info_btcusdt.json")["symbols"][0]
    rules = parse.parse_rules(info, InstrumentType.LINEAR_PERPETUAL)
    assert rules.tick_size == Decimal("0.10")
    assert rules.lot_step == Decimal("0.001")
    assert rules.min_notional == Decimal(50)
    assert rules.maintenance_margin_fraction == Decimal("0.025")


def test_rule_comparison_ignores_the_raw_payload() -> None:
    info = load("binance_spot/exchange_info_btcusdt.json")["symbols"][0]
    first = parse.parse_rules(info, InstrumentType.SPOT)
    changed = parse.parse_rules({**info, "permissions": ["X"]}, InstrumentType.SPOT)
    assert first.same_terms_as(changed)


def test_force_order_parses() -> None:
    data = {"o": {"S": "SELL", "T": 1793607887499, "ap": "78000.1", "q": "0.014"}}
    sample = parse.parse_force_order(data, 1, 1, NOW)
    assert sample.side == "SELL"
    assert sample.quantity == Decimal("0.014")


def test_parsing_is_deterministic() -> None:
    row = load("binance_spot/klines_btcusdt_1m.json")[0]
    server_time = NOW + timedelta(days=1)
    assert parse.parse_rest_kline(row, context(), server_time) == parse.parse_rest_kline(
        row, context(), server_time
    )


@given(st.integers(min_value=1_230_768_000_000, max_value=4_102_444_800_000))
def test_plausible_timestamps_round_trip(value: int) -> None:
    assert parse.timestamp(value).tzinfo is UTC


@given(st.integers().filter(lambda v: not 1_230_768_000_000 <= v <= 4_102_444_800_000))
def test_implausible_timestamps_are_always_rejected(value: int) -> None:
    with pytest.raises(MalformedFrame):
        parse.timestamp(value)
