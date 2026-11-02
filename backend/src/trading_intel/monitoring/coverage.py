"""Coverage over a window. Reports must show gaps honestly, so this is computed, not assumed."""

from dataclasses import dataclass
from datetime import datetime

from trading_intel.database.repositories.candles import CandleRepository
from trading_intel.database.repositories.operations import (
    EventRepository,
    GapRepository,
    SnapshotRepository,
)
from trading_intel.database.repositories.reference import ReferenceRepository
from trading_intel.domain.candles import Timeframe


@dataclass(frozen=True)
class InstrumentCoverage:
    provider: str
    instrument_id: int
    symbol: str
    candles_expected: int
    candles_stored: int
    gaps_repaired: int
    gaps_provider_missing: int
    spread_minutes_recorded: int
    spread_minutes_lost: int


@dataclass(frozen=True)
class Downtime:
    reason: str
    provider: str | None
    start: datetime
    end: datetime


@dataclass(frozen=True)
class CoverageReport:
    window_start: datetime
    window_end: datetime
    instruments: list[InstrumentCoverage]
    downtime: list[Downtime]


class CoverageService:
    def __init__(
        self,
        reference: ReferenceRepository,
        candles: CandleRepository,
        gaps: GapRepository,
        snapshots: SnapshotRepository,
        events: EventRepository,
    ) -> None:
        self._reference = reference
        self._candles = candles
        self._gaps = gaps
        self._snapshots = snapshots
        self._events = events

    async def report(self, start: datetime, end: datetime) -> CoverageReport:
        first = Timeframe.M1.next_open(Timeframe.M1.floor(start))
        last = Timeframe.M1.floor(end)
        expected = max((last - first) // Timeframe.M1.delta, 0)
        items: list[InstrumentCoverage] = []
        for entry in await self._reference.provider_instruments():
            if entry.provider_code == "synthetic":
                continue
            stored = await self._candles.open_times(
                entry.provider_id, entry.instrument.id, Timeframe.M1, first, last
            )
            gaps = await self._gaps.list(
                provider_id=entry.provider_id, instrument_id=entry.instrument.id
            )
            inside = [g for g in gaps if g.gap_start < last and g.gap_end > first]
            recorded = await self._snapshots.spread_minutes(
                entry.provider_id, entry.instrument.id, first, last
            )
            items.append(
                InstrumentCoverage(
                    provider=entry.provider_code,
                    instrument_id=entry.instrument.id,
                    symbol=entry.instrument.symbol,
                    candles_expected=expected,
                    candles_stored=len(stored),
                    gaps_repaired=sum(g.state == "repaired" for g in inside),
                    gaps_provider_missing=sum(g.state == "provider_missing" for g in inside),
                    spread_minutes_recorded=recorded,
                    spread_minutes_lost=max(expected - recorded, 0),
                )
            )
        downtime = [
            Downtime(
                reason=row["reason"],
                provider=row.get("provider"),
                start=datetime.fromisoformat(row["start"]),
                end=datetime.fromisoformat(row["end"]),
            )
            for row in await self._events.downtime(start, end)
        ]
        return CoverageReport(start, end, items, downtime)
