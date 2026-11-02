import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from trading_intel.core.clock import to_epoch_ms
from trading_intel.domain.base import DataOrigin
from trading_intel.domain.candles import ClosedCandle, FormingCandle, Timeframe

OPEN = datetime(2026, 1, 1, tzinfo=UTC)
BACKEND = Path(__file__).resolve().parents[2]


def candle_fields(**overrides: Any) -> dict[str, Any]:
    timeframe = overrides.get("timeframe", Timeframe.M1)
    open_time = overrides.get("open_time", OPEN)
    values: dict[str, Any] = {
        "provider_id": 1,
        "instrument_id": 1,
        "timeframe": timeframe,
        "open_time": open_time,
        "close_time": timeframe.close_time(open_time),
        "open": Decimal(100),
        "high": Decimal(110),
        "low": Decimal(90),
        "close": Decimal(105),
        "volume": Decimal(5),
        "quote_volume": Decimal(500),
        "trade_count": 3,
        "provider_open_time_raw": to_epoch_ms(open_time),
        "data_origin": DataOrigin.BACKFILL,
        "received_at": OPEN + timedelta(minutes=2),
    }
    return {**values, **overrides}


def test_valid_candle_builds() -> None:
    assert ClosedCandle(**candle_fields()).close == Decimal(105)


@pytest.mark.parametrize("model", [ClosedCandle, FormingCandle])
def test_float_price_is_rejected(model: type[ClosedCandle] | type[FormingCandle]) -> None:
    with pytest.raises(ValidationError):
        model(**candle_fields(open=100.0))


def test_string_price_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ClosedCandle(**candle_fields(close="105"))


def test_candles_are_immutable() -> None:
    candle = ClosedCandle(**candle_fields())
    with pytest.raises(ValidationError):
        candle.close = Decimal(1)  # type: ignore[misc]


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"high": Decimal(99)}, "high_below_body"),
        ({"low": Decimal(101)}, "low_above_body"),
        ({"low": Decimal(0)}, "non_positive_price"),
        ({"volume": Decimal(-1)}, "negative_volume"),
        ({"trade_count": -1}, "negative_trade_count"),
        ({"open_time": OPEN + timedelta(seconds=1)}, "open_time_misaligned"),
        ({"close_time": OPEN + timedelta(minutes=1)}, "close_time_mismatch"),
    ],
)
def test_invalid_candle_gives_a_named_reason(overrides: dict[str, Any], reason: str) -> None:
    with pytest.raises(ValidationError, match=reason):
        ClosedCandle(**candle_fields(**overrides))


def test_zero_volume_candle_is_valid() -> None:
    flat = {name: Decimal(100) for name in ("open", "high", "low", "close")}
    candle = ClosedCandle(
        **candle_fields(**flat, volume=Decimal(0), quote_volume=Decimal(0), trade_count=0)
    )
    assert candle.trade_count == 0


@pytest.mark.parametrize("timeframe", list(Timeframe))
def test_boundary_times_for_every_timeframe(timeframe: Timeframe) -> None:
    open_time = datetime(2026, 3, 1, tzinfo=UTC)
    close_time = timeframe.close_time(open_time)
    assert timeframe.is_aligned(open_time)
    assert not timeframe.is_aligned(open_time + timedelta(seconds=1))
    assert close_time + timedelta(milliseconds=1) == timeframe.next_open(open_time)
    assert to_epoch_ms(close_time) % 1000 == 999
    assert timeframe.floor(close_time) == open_time
    assert timeframe.floor(timeframe.next_open(open_time)) == timeframe.next_open(open_time)


def test_seven_timeframes_exist() -> None:
    assert [t.value for t in Timeframe] == ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]


@given(
    timeframe=st.sampled_from(list(Timeframe)),
    moment=st.datetimes(
        min_value=datetime(2017, 1, 1),  # noqa: DTZ001
        max_value=datetime(2035, 1, 1),  # noqa: DTZ001
        timezones=st.just(UTC),
    ),
)
def test_floor_is_aligned_and_contains_the_moment(timeframe: Timeframe, moment: datetime) -> None:
    opened = timeframe.floor(moment)
    assert timeframe.is_aligned(opened)
    assert opened <= moment < timeframe.next_open(opened)


def test_mypy_rejects_a_forming_candle_where_a_closed_one_is_required(tmp_path: Path) -> None:
    sample = tmp_path / "typing_sample.py"
    sample.write_text(
        "from trading_intel.domain.candles import ClosedCandle, FormingCandle\n"
        "def analyse(candle: ClosedCandle) -> None: ...\n"
        "def caller(candle: FormingCandle) -> None:\n"
        "    analyse(candle)\n"
    )
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "mypy", "--strict", "--config-file=", str(sample)],
        capture_output=True,
        text=True,
        cwd=BACKEND,
        check=False,
        env={"MYPYPATH": str(BACKEND / "src")},
    )
    assert result.returncode == 1, result.stdout
    assert 'incompatible type "FormingCandle"' in result.stdout
