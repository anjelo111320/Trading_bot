"""Seeded synthetic candles for quant tests. This is test data, not market data."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np

from trading_intel.core.clock import to_epoch_ms
from trading_intel.domain.base import DataOrigin
from trading_intel.domain.candles import ClosedCandle, Timeframe
from trading_intel.technical_analysis.series import CandleSeries

START = datetime(2026, 1, 1, tzinfo=UTC)


def _round(value: float) -> Decimal:
    return Decimal(f"{value:.2f}")


def candle(
    index: int,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float = 10.0,
    timeframe: Timeframe = Timeframe.H1,
    taker: float | None = None,
) -> ClosedCandle:
    open_time = START + timeframe.delta * index
    return ClosedCandle(
        provider_id=1,
        instrument_id=1,
        timeframe=timeframe,
        open_time=open_time,
        close_time=timeframe.close_time(open_time),
        open=_round(open_),
        high=_round(high),
        low=_round(low),
        close=_round(close),
        volume=_round(volume),
        quote_volume=_round(volume * close),
        taker_buy_base_volume=None if taker is None else _round(taker),
        trade_count=10,
        provider_open_time_raw=to_epoch_ms(open_time),
        data_origin=DataOrigin.SYNTHETIC,
        received_at=open_time + timedelta(hours=1),
    )


def random_walk(count: int, seed: int, timeframe: Timeframe = Timeframe.H1) -> CandleSeries:
    rng = np.random.default_rng(seed)
    price = 1000.0
    candles: list[ClosedCandle] = []
    for index in range(count):
        drift = float(rng.normal(0, 4))
        close = max(price + drift, 10.0)
        high = max(price, close) + float(rng.uniform(0, 3))
        low = max(min(price, close) - float(rng.uniform(0, 3)), 1.0)
        volume = float(rng.uniform(5, 50))
        candles.append(
            candle(index, price, high, low, close, volume, timeframe, taker=volume * 0.5)
        )
        price = close
    return CandleSeries.of(candles)


def from_closes(closes: list[float], spread: float = 1.0) -> CandleSeries:
    """Candles that open at the previous close, with a fixed wick."""
    candles: list[ClosedCandle] = []
    previous = closes[0]
    for index, close in enumerate(closes):
        candles.append(
            candle(
                index, previous, max(previous, close) + spread, min(previous, close) - spread, close
            )
        )
        previous = close
    return CandleSeries.of(candles)
