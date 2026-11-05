"""Re-analysis jobs: one at a time, with a clear result either way."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from trading_intel.api.forecast_jobs import AnalysisJobs
from trading_intel.core.clock import FixedClock
from trading_intel.core.errors import ConflictError
from trading_intel.forecasting.kronos import ForecastUnavailableError, exclusive

NOW = datetime(2026, 11, 5, 3, 5, tzinfo=UTC)
AS_OF = datetime(2026, 11, 5, 2, 59, 59, 999000, tzinfo=UTC)


async def test_a_job_runs_in_the_background_and_records_its_note() -> None:
    jobs = AnalysisJobs(FixedClock(NOW))
    release = asyncio.Event()

    async def work() -> str | None:
        await release.wait()
        return "kept the stored forecast"

    job = jobs.start(3, "BTCUSDT", AS_OF, work)
    assert job.state == "running" and job.started_at == NOW
    with pytest.raises(ConflictError, match="BTCUSDT is already running"):
        jobs.start(4, "ETHUSDT", AS_OF, work)
    release.set()
    await jobs.wait()
    assert jobs.current is not None
    assert jobs.current.state == "succeeded"
    assert jobs.current.message == "kept the stored forecast"


async def test_a_failed_job_says_why_and_frees_the_slot() -> None:
    jobs = AnalysisJobs(FixedClock(NOW))

    async def stale() -> str | None:
        raise ForecastUnavailableError("the candle closing at 02:59 is too old")

    async def broken() -> str | None:
        raise RuntimeError("bug")

    jobs.start(3, "BTCUSDT", AS_OF, stale)
    await jobs.wait()
    assert jobs.current is not None and jobs.current.state == "failed"
    assert jobs.current.message == "the candle closing at 02:59 is too old"
    jobs.start(3, "BTCUSDT", AS_OF, broken)
    await jobs.wait()
    assert jobs.current.message == "The analysis failed unexpectedly. See the API log."


def test_only_one_process_holds_the_kronos_lock(tmp_path: Path) -> None:
    lock = tmp_path / "kronos.lock"
    with exclusive(lock), pytest.raises(BlockingIOError), exclusive(lock, wait=False):
        pass
    with exclusive(lock, wait=False):
        pass
