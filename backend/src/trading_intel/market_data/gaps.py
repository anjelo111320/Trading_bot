"""Find missing candles and repair them from the provider. Nothing is ever filled in."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import structlog

from trading_intel.core.clock import Clock
from trading_intel.data_providers.base import MarketDataProvider
from trading_intel.database.repositories.candles import CandleRepository
from trading_intel.database.repositories.operations import GapRepository
from trading_intel.domain.base import DataOrigin
from trading_intel.domain.candles import ClosedCandle, Timeframe
from trading_intel.domain.instruments import Instrument

log = structlog.get_logger(__name__)

WRITE_BATCH = 1000


def missing_ranges(
    open_times: Sequence[datetime], timeframe: Timeframe, start: datetime, end: datetime
) -> list[tuple[datetime, datetime]]:
    """Missing open times in [start, end), as half-open ranges. Input must be sorted.

    Klines have no sequence number, so continuity of open times is the only signal.
    """
    gaps: list[tuple[datetime, datetime]] = []
    expected = start
    for open_time in open_times:
        if open_time > expected:
            gaps.append((expected, open_time))
        expected = timeframe.next_open(open_time)
    if expected < end:
        gaps.append((expected, end))
    return gaps


async def store_in_batches(
    provider: MarketDataProvider,
    candles: CandleRepository,
    instrument: Instrument,
    timeframe: Timeframe,
    start: datetime,
    end: datetime,
    origin: DataOrigin,
) -> int:
    """Copy a range from the provider. Returns how many rows were new."""
    inserted = 0
    batch: list[ClosedCandle] = []
    async for candle in provider.get_historical_candles(instrument, timeframe, start, end, origin):
        batch.append(candle)
        if len(batch) >= WRITE_BATCH:
            inserted += await candles.insert(batch)
            batch = []
    return inserted + await candles.insert(batch)


@dataclass(frozen=True)
class RepairResult:
    found: int
    repaired: int
    provider_missing: int
    rows_recovered: int


class GapRepairService:
    def __init__(
        self,
        provider: MarketDataProvider,
        provider_id: int,
        candles: CandleRepository,
        gaps: GapRepository,
        clock: Clock,
    ) -> None:
        self._provider = provider
        self._provider_id = provider_id
        self._candles = candles
        self._gaps = gaps
        self._clock = clock

    async def repair(
        self,
        instrument: Instrument,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
        cause: str = "ingest_failure",
    ) -> RepairResult:
        """Repair [start, end). Every missing range ends up in market_gaps."""
        ranges = await self._missing(instrument, timeframe, start, end)
        repaired = provider_missing = recovered = 0
        for gap_start, gap_end in ranges:
            await self._gaps.record(
                self._provider_id, instrument.id, timeframe, gap_start, gap_end, cause
            )
            await self._gaps.set_state(
                self._provider_id, instrument.id, timeframe, gap_start, "repairing"
            )
            recovered += await store_in_batches(
                self._provider,
                self._candles,
                instrument,
                timeframe,
                gap_start,
                gap_end,
                DataOrigin.BACKFILL,
            )
            remaining = await self._missing(instrument, timeframe, gap_start, gap_end)
            if remaining:
                provider_missing += 1
                await self._gaps.set_state(
                    self._provider_id,
                    instrument.id,
                    timeframe,
                    gap_start,
                    "provider_missing",
                    self._clock.now(),
                )
                log.warning(
                    "gap_provider_missing",
                    instrument=instrument.symbol,
                    timeframe=timeframe.value,
                    start=gap_start.isoformat(),
                )
            else:
                repaired += 1
                await self._gaps.set_state(
                    self._provider_id,
                    instrument.id,
                    timeframe,
                    gap_start,
                    "repaired",
                    self._clock.now(),
                )
        return RepairResult(len(ranges), repaired, provider_missing, recovered)

    async def _missing(
        self, instrument: Instrument, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[tuple[datetime, datetime]]:
        stored = await self._candles.open_times(
            self._provider_id, instrument.id, timeframe, start, end
        )
        return missing_ranges(stored, timeframe, start, end)
