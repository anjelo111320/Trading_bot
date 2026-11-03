"""Historical candle loading. Resumable, idempotent, and refuses to fill the disk."""

import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import structlog

from trading_intel.core.clock import Clock
from trading_intel.core.errors import AppError
from trading_intel.data_providers.base import MarketDataProvider
from trading_intel.database.repositories.candles import CandleRepository
from trading_intel.database.repositories.operations import GapRepository, RunRepository
from trading_intel.domain.base import DataOrigin
from trading_intel.domain.candles import Timeframe
from trading_intel.domain.instruments import Instrument, InstrumentType
from trading_intel.market_data.gaps import missing_ranges, store_in_batches

log = structlog.get_logger(__name__)

BYTES_PER_ROW: Final = 250  # Measured at 245.5 on synthetic rows, rounded up.
GIB: Final = 1024**3
ALL_TIMEFRAMES: Final = tuple(Timeframe)
SPOT_HISTORY_TIMEFRAMES: Final = (
    Timeframe.M15,
    Timeframe.M30,
    Timeframe.H1,
    Timeframe.H4,
    Timeframe.D1,
)


class BackfillRefusedError(AppError):
    code = "backfill_refused"


@dataclass(frozen=True)
class BackfillProfile:
    """What to load. Earliest dates are the first data Binance holds per instrument."""

    name: str
    floor_bytes: int
    window: timedelta | None  # Recent window, or None for full history.
    spot_timeframes: tuple[Timeframe, ...]


TEST_PROFILE: Final = BackfillProfile("test", 2 * GIB, timedelta(days=90), ALL_TIMEFRAMES)
# Real candles from before the frozen holdout, so the engine can run without spending it (D029).
RESEARCH_START: Final = datetime(2025, 6, 25, tzinfo=UTC)
RESEARCH_END: Final = datetime(2025, 11, 1, tzinfo=UTC)
RESEARCH_TIMEFRAMES: Final = (Timeframe.M1, Timeframe.M15, Timeframe.H1, Timeframe.H4)
FULL_PROFILE: Final = BackfillProfile("full", 10 * GIB, None, SPOT_HISTORY_TIMEFRAMES)
# 1H setups need long perpetual history, but only from 15M up, which fits this computer (D034).
HISTORY_TIMEFRAMES: Final = (Timeframe.M15, Timeframe.H1, Timeframe.H4, Timeframe.D1)
HISTORY_PROFILE: Final = BackfillProfile("history", 2 * GIB, None, ())


@dataclass(frozen=True)
class BackfillTask:
    instrument: Instrument
    timeframe: Timeframe
    start: datetime
    end: datetime

    @property
    def expected_rows(self) -> int:
        return max((self.end - self.start) // self.timeframe.delta, 0)


@dataclass
class BackfillReport:
    tasks: int = 0
    rows_added: int = 0
    rows_expected: int = 0
    gaps: int = 0
    per_task: list[dict[str, object]] = field(default_factory=list)


def plan_tasks(
    instruments: Sequence[tuple[Instrument, datetime]],
    profile: BackfillProfile,
    now: datetime,
) -> list[BackfillTask]:
    """Build tasks ending at the latest closed candle of each timeframe."""
    tasks: list[BackfillTask] = []
    for instrument, earliest in instruments:
        timeframes = (
            profile.spot_timeframes
            if instrument.instrument_type is InstrumentType.SPOT
            else ALL_TIMEFRAMES
        )
        for timeframe in timeframes:
            end = timeframe.floor(now)
            start = earliest
            if profile.window is not None:
                start = max(earliest, timeframe.floor(now - profile.window))
            tasks.append(BackfillTask(instrument, timeframe, _aligned(timeframe, start), end))
    return tasks


def plan_research_tasks(instruments: Sequence[Instrument]) -> list[BackfillTask]:
    return [
        BackfillTask(instrument, timeframe, RESEARCH_START, RESEARCH_END)
        for instrument in instruments
        for timeframe in RESEARCH_TIMEFRAMES
    ]


def plan_history_tasks(instruments: Sequence[tuple[Instrument, datetime]]) -> list[BackfillTask]:
    """Perpetuals from listing up to the frozen holdout, which this profile never reads."""
    return [
        BackfillTask(instrument, timeframe, _aligned(timeframe, earliest), RESEARCH_END)
        for instrument, earliest in instruments
        if instrument.instrument_type is not InstrumentType.SPOT
        for timeframe in HISTORY_TIMEFRAMES
    ]


def _aligned(timeframe: Timeframe, start: datetime) -> datetime:
    floor = timeframe.floor(start)
    return floor if floor == start else timeframe.next_open(floor)


def disk_free_bytes(path: Path = Path("/")) -> int:
    return shutil.disk_usage(path).free


class BackfillService:
    def __init__(
        self,
        provider: MarketDataProvider,
        provider_id: int,
        candles: CandleRepository,
        gaps: GapRepository,
        runs: RunRepository,
        clock: Clock,
        *,
        free_bytes: Callable[[], int] = disk_free_bytes,
        git_sha: str = "unknown",
    ) -> None:
        self._provider = provider
        self._provider_id = provider_id
        self._candles = candles
        self._gaps = gaps
        self._runs = runs
        self._clock = clock
        self._free_bytes = free_bytes
        self._git_sha = git_sha

    async def run(self, tasks: Sequence[BackfillTask], floor_bytes: int) -> BackfillReport:
        await self._refuse_if_disk_would_run_out(tasks, floor_bytes)
        run_id = await self._runs.start(self._provider_id, "backfill", self._git_sha)
        report = BackfillReport(tasks=len(tasks))
        try:
            for task in tasks:
                self._check_floor(floor_bytes)
                await self._load(task, report)
        except Exception:
            await self._runs.finish(run_id, "failed", _stats(report))
            raise
        await self._runs.finish(run_id, "succeeded", _stats(report))
        return report

    def _check_floor(self, floor_bytes: int) -> None:
        """Free space moves with swap and other apps, so check before every task."""
        free = self._free_bytes()
        if free < floor_bytes:
            raise BackfillRefusedError(
                f"stopped with {free / GIB:.1f} GiB free, below the "
                f"{floor_bytes / GIB:.1f} GiB floor"
            )

    async def _refuse_if_disk_would_run_out(
        self, tasks: Sequence[BackfillTask], floor_bytes: int
    ) -> None:
        remaining_rows = 0
        for task in tasks:
            stored = await self._candles.open_times(
                self._provider_id, task.instrument.id, task.timeframe, task.start, task.end
            )
            remaining_rows += max(task.expected_rows - len(stored), 0)
        needed = remaining_rows * BYTES_PER_ROW
        after = self._free_bytes() - needed
        if after < floor_bytes:
            raise BackfillRefusedError(
                f"backfill would leave {after / GIB:.1f} GiB free, below the "
                f"{floor_bytes / GIB:.1f} GiB floor"
            )

    async def _load(self, task: BackfillTask, report: BackfillReport) -> None:
        """Fetch only what is missing, so older ranges and interrupted runs both work."""
        stored = await self._candles.open_times(
            self._provider_id, task.instrument.id, task.timeframe, task.start, task.end
        )
        added = 0
        for hole_start, hole_end in missing_ranges(stored, task.timeframe, task.start, task.end):
            added += await store_in_batches(
                self._provider,
                self._candles,
                task.instrument,
                task.timeframe,
                hole_start,
                hole_end,
                DataOrigin.BACKFILL,
            )
        stored = await self._candles.open_times(
            self._provider_id, task.instrument.id, task.timeframe, task.start, task.end
        )
        holes = missing_ranges(stored, task.timeframe, task.start, task.end)
        for gap_start, gap_end in holes:
            await self._gaps.record(
                self._provider_id,
                task.instrument.id,
                task.timeframe,
                gap_start,
                gap_end,
                "provider_missing",
            )
            await self._gaps.set_state(
                self._provider_id,
                task.instrument.id,
                task.timeframe,
                gap_start,
                "provider_missing",
                self._clock.now(),
            )
        report.rows_added += added
        report.rows_expected += task.expected_rows
        report.gaps += len(holes)
        report.per_task.append(
            {
                "instrument": task.instrument.symbol,
                "type": task.instrument.instrument_type.value,
                "timeframe": task.timeframe.value,
                "expected": task.expected_rows,
                "stored": len(stored),
                "added": added,
                "gaps": len(holes),
            }
        )
        log.info(
            "backfill_task_done",
            instrument=task.instrument.symbol,
            timeframe=task.timeframe.value,
            added=added,
            stored=len(stored),
        )


def _stats(report: BackfillReport) -> dict[str, object]:
    return {
        "tasks": report.tasks,
        "rows_added": report.rows_added,
        "rows_expected": report.rows_expected,
        "gaps": report.gaps,
    }
