"""Down warnings on synthetic candles."""

from tests.quant_data import candle
from trading_intel.domain.candles import ClosedCandle, Timeframe
from trading_intel.market_structure.shock import down_warnings
from trading_intel.technical_analysis.series import CandleSeries


def quiet(count: int = 30) -> list[ClosedCandle]:
    """A flat market around 100, volume 10, takers balanced."""
    return [
        candle(i, 100.0, 100.5, 99.5, 100.0, 10.0, Timeframe.H1).model_copy(
            update={"taker_buy_base_volume": 5, "taker_buy_quote_volume": 500}
        )
        for i in range(count)
    ]


def last(
    rows: list[ClosedCandle], close: float, volume: float, bought: float | None
) -> list[ClosedCandle]:
    final = candle(len(rows), 100.0, 100.0, close - 0.2, close, volume, Timeframe.H1)
    taker = None if bought is None else bought
    return [*rows, final.model_copy(update={"taker_buy_base_volume": taker})]


def warns(rows: list[ClosedCandle]) -> bool:
    return bool(down_warnings(CandleSeries.of(rows))[-1])


def test_a_heavy_close_below_the_range_with_sellers_in_control_warns() -> None:
    assert warns(last(quiet(), close=99.0, volume=25.0, bought=10.0))


def test_a_close_inside_the_range_does_not_warn() -> None:
    assert not warns(last(quiet(), close=99.8, volume=25.0, bought=10.0))


def test_ordinary_volume_does_not_warn() -> None:
    assert not warns(last(quiet(), close=99.0, volume=15.0, bought=5.0))


def test_buyers_in_control_do_not_warn() -> None:
    assert not warns(last(quiet(), close=99.0, volume=25.0, bought=12.0))


def test_missing_taker_data_never_warns() -> None:
    assert not warns(last(quiet(), close=99.0, volume=25.0, bought=None))


def test_a_warning_uses_only_candles_up_to_it() -> None:
    rows = last(quiet(), close=99.0, volume=25.0, bought=10.0)
    after = [
        candle(len(rows) + i, 99.0, 99.5, 98.5, 99.0, 50.0, Timeframe.H1).model_copy(
            update={"taker_buy_base_volume": 10}
        )
        for i in range(5)
    ]
    full = down_warnings(CandleSeries.of([*rows, *after]))
    prefix = down_warnings(CandleSeries.of(rows))
    assert list(full[: len(rows)]) == list(prefix)
    assert prefix[-1], "the test case should warn"
