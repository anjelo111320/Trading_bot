"""Check stored live data against the provider over a window. Read-only.

Usage: uv run python scripts/soak_report.py --since 2026-11-02T09:33:00Z
"""

import argparse
import asyncio
import json
from datetime import datetime
from typing import Any

from trading_intel.core.clock import SystemClock, ensure_utc
from trading_intel.core.settings import load_settings
from trading_intel.database.engine import create_engine
from trading_intel.database.repositories.candles import CandleRepository, differences
from trading_intel.database.repositories.operations import GapRepository
from trading_intel.database.repositories.reference import ReferenceRepository
from trading_intel.domain.candles import Timeframe
from trading_intel.entrypoints.wiring import BINANCE_SPOT, BINANCE_USDM, build_provider
from trading_intel.market_data.gaps import missing_ranges
from trading_intel.monitoring.coverage import CoverageService


async def check(since: datetime) -> dict[str, Any]:
    settings = load_settings()
    clock = SystemClock()
    engine = create_engine(settings.database_url)
    reference = ReferenceRepository(engine)
    candles = CandleRepository(engine)
    gaps = GapRepository(engine)
    now = clock.now()
    rows_checked = 0
    missing: list[str] = []
    mismatches: list[str] = []
    for code in (BINANCE_SPOT, BINANCE_USDM):
        listed = await reference.provider_instruments(code)
        provider = build_provider(code, settings, clock, listed)
        for item in listed:
            for timeframe in Timeframe:
                start = timeframe.next_open(timeframe.floor(since))
                end = timeframe.floor(now)
                if start >= end:
                    continue
                stored = {
                    c.open_time: c
                    for c in await candles.range(
                        item.provider_id, item.instrument.id, timeframe, start, end
                    )
                }
                holes = missing_ranges(sorted(stored), timeframe, start, end)
                label = f"{code} {item.instrument.symbol} {timeframe.value}"
                missing += [f"{label} {a.isoformat()} to {b.isoformat()}" for a, b in holes]
                async for remote in provider.get_historical_candles(
                    item.instrument, timeframe, start, end
                ):
                    rows_checked += 1
                    local = stored.get(remote.open_time)
                    if local is not None and (fields := differences(local, remote)):
                        mismatches.append(f"{label} {remote.open_time.isoformat()} {fields}")
        await provider.disconnect()
    unresolved = await gaps.list(states=("detected", "repairing"))
    return {
        "window_start": since.isoformat(),
        "window_end": now.isoformat(),
        "rows_compared_with_provider": rows_checked,
        "missing_ranges": missing,
        "value_mismatches": mismatches,
        "unresolved_gaps": len(unresolved),
        "coverage": await _coverage(engine, reference, candles, gaps, since, now),
    }


async def _coverage(
    engine: Any, reference: Any, candles: Any, gaps: Any, start: Any, end: Any
) -> Any:
    from trading_intel.database.repositories.operations import EventRepository, SnapshotRepository

    report = await CoverageService(
        reference, candles, gaps, SnapshotRepository(engine), EventRepository(engine)
    ).report(start, end)
    return {
        "instruments": [vars(i) for i in report.instruments],
        "downtime": [
            {**vars(d), "start": str(d.start), "end": str(d.end)} for d in report.downtime
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", required=True)
    arguments = parser.parse_args()
    since = ensure_utc(datetime.fromisoformat(arguments.since.replace("Z", "+00:00")))
    print(json.dumps(asyncio.run(check(since)), indent=1))


if __name__ == "__main__":
    main()
