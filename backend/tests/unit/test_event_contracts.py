import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid7

from tests.unit.test_candles import candle_fields
from trading_intel.domain.base import DataOrigin
from trading_intel.domain.candles import ClosedCandle, FormingCandle
from trading_intel.domain.events import (
    MARKET_CANDLE,
    MARKET_PRICE,
    MARKET_STATUS,
    EventEnvelope,
    candle_payload,
    event_json_schemas,
    plain,
)


def test_every_phase_one_event_has_a_json_schema() -> None:
    schemas = event_json_schemas()
    assert set(schemas) == {"envelope", MARKET_PRICE, MARKET_CANDLE, MARKET_STATUS}
    json.dumps(schemas)


def test_envelope_has_the_documented_fields() -> None:
    required = set(event_json_schemas()["envelope"]["required"])
    assert required == {
        "event_id",
        "event_type",
        "schema_version",
        "occurred_at",
        "seq",
        "data_origin",
        "payload",
    }


def test_envelope_round_trips_through_json() -> None:
    envelope = EventEnvelope(
        event_id=uuid7(),
        event_type=MARKET_PRICE,
        schema_version=1,
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        seq=7,
        data_origin=DataOrigin.LIVE,
        payload={"bid": "1.5"},
    )
    assert EventEnvelope.model_validate_json(envelope.model_dump_json()) == envelope


def test_money_on_the_wire_is_a_plain_string() -> None:
    payload = candle_payload("binance_spot", ClosedCandle(**candle_fields()))
    assert payload.close == "105"
    assert plain(Decimal("0E-8")) == "0.00000000"


def test_payload_states_whether_the_candle_is_closed() -> None:
    assert candle_payload("p", ClosedCandle(**candle_fields())).is_closed is True
    assert candle_payload("p", FormingCandle(**candle_fields())).is_closed is False
