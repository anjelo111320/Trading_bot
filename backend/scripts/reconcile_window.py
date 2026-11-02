"""Correct stored candles against final provider values, leaving a revision for each one.

Usage: uv run python scripts/reconcile_window.py --since 2026-11-02T09:47:00Z --reason "..."
Windows that end within a minute of now are cut short, because recent values are not final.
"""

import argparse
import asyncio
from datetime import datetime, timedelta

from trading_intel.core.clock import SystemClock, ensure_utc
from trading_intel.core.settings import load_settings
from trading_intel.database.engine import create_engine
from trading_intel.database.repositories.candles import CandleRepository, differences
from trading_intel.database.repositories.reference import ReferenceRepository
from trading_intel.domain.candles import Timeframe
from trading_intel.entrypoints.wiring import BINANCE_SPOT, BINANCE_USDM, build_provider

SETTLE = timedelta(minutes=1)


async def run(since: datetime, reason: str) -> None:
    settings = load_settings()
    clock = SystemClock()
    engine = create_engine(settings.ingest_database_url)
    reference = ReferenceRepository(engine)
    candles = CandleRepository(engine)
    end_time = clock.now() - SETTLE
    corrected = 0
    for code in (BINANCE_SPOT, BINANCE_USDM):
        listed = await reference.provider_instruments(code)
        provider = build_provider(code, settings, clock, listed)
        for item in listed:
            for timeframe in Timeframe:
                start, end = timeframe.floor(since), timeframe.floor(end_time)
                if start >= end:
                    continue
                stored = {
                    c.open_time: c
                    for c in await candles.range(
                        item.provider_id, item.instrument.id, timeframe, start, end
                    )
                }
                async for remote in provider.get_historical_candles(
                    item.instrument, timeframe, start, end
                ):
                    local = stored.get(remote.open_time)
                    if local is not None and (fields := differences(local, remote)):
                        await candles.replace_with_revision(
                            local, remote, f"{reason}: {', '.join(fields)}"
                        )
                        corrected += 1
                        print(code, item.instrument.symbol, timeframe.value, remote.open_time)
        await provider.disconnect()
    await engine.dispose()
    print("corrected", corrected)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", required=True)
    parser.add_argument("--reason", required=True)
    arguments = parser.parse_args()
    since = ensure_utc(datetime.fromisoformat(arguments.since.replace("Z", "+00:00")))
    asyncio.run(run(since, arguments.reason))


if __name__ == "__main__":
    main()
