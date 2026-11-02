"""Market responses. Money is a string on the wire, and origin is always stated."""

from typing import Literal

from pydantic import BaseModel

from trading_intel.core.clock import UtcDatetime
from trading_intel.domain.base import DataOrigin
from trading_intel.domain.candles import ClosedCandle, Timeframe
from trading_intel.domain.events import plain
from trading_intel.domain.instruments import InstrumentType
from trading_intel.monitoring.coverage import CoverageReport

FeedStateName = Literal["HEALTHY", "DEGRADED", "STALE", "DISCONNECTED", "RECOVERING"]


class InstrumentView(BaseModel):
    id: int
    symbol: str
    instrument_type: InstrumentType
    base_asset: str
    quote_asset: str
    provider: str
    provider_symbol: str
    is_synthetic: bool
    tick_size: str | None


class CandleView(BaseModel):
    open_time: UtcDatetime
    close_time: UtcDatetime
    open: str
    high: str
    low: str
    close: str
    volume: str
    quote_volume: str
    trade_count: int
    data_origin: DataOrigin

    @classmethod
    def of(cls, candle: ClosedCandle) -> CandleView:
        return cls(
            open_time=candle.open_time,
            close_time=candle.close_time,
            open=plain(candle.open),
            high=plain(candle.high),
            low=plain(candle.low),
            close=plain(candle.close),
            volume=plain(candle.volume),
            quote_volume=plain(candle.quote_volume),
            trade_count=candle.trade_count,
            data_origin=candle.data_origin,
        )


class CandlePage(BaseModel):
    provider: str
    instrument_id: int
    timeframe: Timeframe
    items: list[CandleView]
    next_before: UtcDatetime | None


class PriceView(BaseModel):
    provider: str
    instrument_id: int
    bid: str | None
    ask: str | None
    received_at: UtcDatetime | None
    age_seconds: float | None
    stale: bool
    data_origin: DataOrigin | None


class FeedStatusView(BaseModel):
    provider: str
    state: FeedStateName
    reasons: list[str]
    last_event_at: UtcDatetime | None
    lag_seconds: float | None
    open_gaps: int
    clock_skew_ms: float | None


class MarketStatusView(BaseModel):
    usable: bool
    feeds: list[FeedStatusView]


class GapView(BaseModel):
    provider_id: int
    instrument_id: int
    timeframe: Timeframe
    gap_start: UtcDatetime
    gap_end: UtcDatetime
    state: str
    cause: str | None
    detected_at: UtcDatetime
    resolved_at: UtcDatetime | None


class GapList(BaseModel):
    items: list[GapView]


class InstrumentCoverageView(BaseModel):
    provider: str
    instrument_id: int
    symbol: str
    candles_expected: int
    candles_stored: int
    gaps_repaired: int
    gaps_provider_missing: int
    spread_minutes_recorded: int
    spread_minutes_lost: int


class DowntimeView(BaseModel):
    reason: str
    provider: str | None
    start: UtcDatetime
    end: UtcDatetime


class CoverageView(BaseModel):
    window_start: UtcDatetime
    window_end: UtcDatetime
    instruments: list[InstrumentCoverageView]
    downtime: list[DowntimeView]

    @classmethod
    def of(cls, report: CoverageReport) -> CoverageView:
        return cls(
            window_start=report.window_start,
            window_end=report.window_end,
            instruments=[InstrumentCoverageView(**vars(item)) for item in report.instruments],
            downtime=[DowntimeView(**vars(item)) for item in report.downtime],
        )
