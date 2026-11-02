from datetime import UTC, datetime, timedelta

from trading_intel.core.clock import FixedClock
from trading_intel.data_providers.base import CandleSubscription, LinkUp
from trading_intel.data_providers.synthetic.provider import SyntheticProvider, price_at
from trading_intel.domain.base import DataOrigin
from trading_intel.domain.candles import ClosedCandle, FormingCandle, Timeframe
from trading_intel.domain.instruments import Instrument, InstrumentType
from trading_intel.domain.market import TopOfBook

NOW = datetime(2026, 6, 1, 12, 0, 30, tzinfo=UTC)
BTC = Instrument(
    id=1,
    symbol="BTCUSDT",
    instrument_type=InstrumentType.SPOT,
    base_asset="BTC",
    quote_asset="USDT",
    settle_asset="USDT",
)


async def history(seed: int) -> list[ClosedCandle]:
    provider = SyntheticProvider(9, FixedClock(NOW), seed=seed)
    start = NOW - timedelta(hours=2)
    return [
        c
        async for c in provider.get_historical_candles(
            BTC, Timeframe.M5, Timeframe.M5.floor(start), NOW
        )
    ]


async def test_the_same_seed_gives_identical_candles() -> None:
    first, second = await history(7), await history(7)
    assert [c.close for c in first] == [c.close for c in second]


async def test_a_different_seed_gives_different_candles() -> None:
    assert [c.close for c in await history(7)] != [c.close for c in await history(8)]


async def test_everything_is_labelled_synthetic_whatever_the_caller_asks() -> None:
    provider = SyntheticProvider(9, FixedClock(NOW))
    start = Timeframe.M1.floor(NOW) - timedelta(minutes=3)
    candles = [
        c
        async for c in provider.get_historical_candles(
            BTC, Timeframe.M1, start, NOW, DataOrigin.BACKFILL
        )
    ]
    assert candles
    assert all(c.data_origin is DataOrigin.SYNTHETIC for c in candles)
    assert all(c.provider_id == 9 for c in candles)


async def test_history_stops_before_the_forming_candle() -> None:
    candles = await history(7)
    assert candles[-1].close_time < NOW


async def test_stream_emits_forming_candles_and_closes_on_the_boundary() -> None:
    clock = FixedClock(NOW)

    async def advance(seconds: float) -> None:
        clock.advance(seconds)

    provider = SyntheticProvider(9, clock, tick_seconds=30, sleep=advance)
    subscription = CandleSubscription(instrument=BTC, timeframe=Timeframe.M1)
    events = []
    async for event in provider.stream_market([subscription], [BTC]):
        events.append(event)
        if len(events) == 6:
            break
    kinds = [type(event) for event in events]
    assert kinds[0] is LinkUp
    assert kinds[1:3] == [FormingCandle, TopOfBook]
    assert ClosedCandle in kinds
    assert all(
        event.data_origin is DataOrigin.SYNTHETIC
        for event in events
        if isinstance(event, ClosedCandle | FormingCandle)
    )


def test_price_is_a_pure_function_of_time() -> None:
    assert price_at(7, 1, NOW) == price_at(7, 1, NOW)
