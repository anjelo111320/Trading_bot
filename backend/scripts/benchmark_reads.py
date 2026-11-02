"""Measure candle reads on the real dataset. Results go in docs/benchmarks/."""

import asyncio
import json
import statistics
import time
from datetime import timedelta

from sqlalchemy import text

from trading_intel.core.settings import load_settings
from trading_intel.database.engine import create_engine
from trading_intel.database.repositories.candles import CandleRepository
from trading_intel.database.repositories.reference import ReferenceRepository
from trading_intel.domain.candles import Timeframe

SAMPLES = 200


async def measure() -> dict[str, object]:
    settings = load_settings()
    engine = create_engine(settings.database_url)
    listed = await ReferenceRepository(engine).provider_instruments("binance_usdm")
    item = listed[0]
    candles = CandleRepository(engine)
    timings: dict[str, list[float]] = {"last_1000": [], "last_500_1h": []}
    for _ in range(SAMPLES):
        start = time.perf_counter()
        await candles.page(item.provider_id, item.instrument.id, Timeframe.M1, 1000)
        timings["last_1000"].append((time.perf_counter() - start) * 1000)
        start = time.perf_counter()
        await candles.page(item.provider_id, item.instrument.id, Timeframe.H1, 500)
        timings["last_500_1h"].append((time.perf_counter() - start) * 1000)
    latest = await candles.latest_open_time(item.provider_id, item.instrument.id, Timeframe.M1)
    assert latest is not None
    start = time.perf_counter()
    rows = await candles.range(
        item.provider_id, item.instrument.id, Timeframe.M1, latest - timedelta(days=80), latest
    )
    long_range = (time.perf_counter() - start) * 1000
    async with engine.connect() as connection:
        total = (await connection.execute(text("SELECT count(*) FROM market_candles"))).scalar_one()
        size = (
            await connection.execute(text("SELECT pg_total_relation_size('market_candles')"))
        ).scalar_one()
    await engine.dispose()
    return {
        "rows_in_table": total,
        "bytes_per_row": round(size / total, 1),
        "last_1000_p50_ms": round(statistics.median(timings["last_1000"]), 2),
        "last_1000_p95_ms": round(statistics.quantiles(timings["last_1000"], n=20)[18], 2),
        "last_500_1h_p95_ms": round(statistics.quantiles(timings["last_500_1h"], n=20)[18], 2),
        "range_rows": len(rows),
        "range_ms": round(long_range, 1),
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(measure()), indent=1))
