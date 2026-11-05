"""Re-analysis requests from the dashboard: one at a time, run in the background.

A request forecasts from the latest stored 1H close. Kronos takes about 90 seconds, so the
request returns at once and the dashboard polls the job. Nothing here can trade.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal

import structlog

from trading_intel.core.clock import Clock
from trading_intel.core.errors import AppError, ConflictError

log = structlog.get_logger(__name__)

JobState = Literal["running", "succeeded", "failed"]


@dataclass(frozen=True)
class AnalysisJob:
    instrument_id: int
    symbol: str
    as_of: datetime  # The 1H close the forecast starts from.
    state: JobState
    started_at: datetime
    finished_at: datetime | None = None
    message: str | None = None


class AnalysisJobs:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._job: AnalysisJob | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def current(self) -> AnalysisJob | None:
        return self._job

    def start(
        self,
        instrument_id: int,
        symbol: str,
        as_of: datetime,
        work: Callable[[], Awaitable[str | None]],
    ) -> AnalysisJob:
        """Run `work` in the background. It returns a note, or raises an AppError to fail."""
        if self._job is not None and self._job.state == "running":
            raise ConflictError(f"An analysis of {self._job.symbol} is already running.")
        job = AnalysisJob(instrument_id, symbol, as_of, "running", self._clock.now())
        self._job = job

        async def run() -> None:
            try:
                note = await work()
            except AppError as error:
                self._finish(job, "failed", error.message)
            except Exception:
                log.exception("analysis_failed", symbol=symbol)
                self._finish(job, "failed", "The analysis failed unexpectedly. See the API log.")
            else:
                self._finish(job, "succeeded", note)

        self._task = asyncio.create_task(run())
        return job

    def _finish(self, job: AnalysisJob, state: JobState, message: str | None) -> None:
        if self._job is job:
            self._job = replace(job, state=state, finished_at=self._clock.now(), message=message)

    async def wait(self) -> None:
        """For tests and shutdown: let the running job finish."""
        if self._task is not None:
            await self._task
