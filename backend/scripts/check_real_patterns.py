"""Run the quant engine over stored real candles and repeat the look-ahead proof on them."""

import asyncio
import sys
import time
from collections import Counter

import numpy as np

from trading_intel.core.clock import SystemClock
from trading_intel.core.settings import load_settings
from trading_intel.database.engine import create_engine
from trading_intel.database.repositories.candles import CandleRepository
from trading_intel.database.repositories.reference import ReferenceRepository
from trading_intel.domain.candles import Timeframe
from trading_intel.domain.patterns import DetectedPattern
from trading_intel.pattern_detection.pipeline import detect_patterns
from trading_intel.technical_analysis.pipeline import compute_indicators
from trading_intel.technical_analysis.series import CandleSeries


async def run(timeframe: Timeframe, limit: int) -> None:
    settings = load_settings()
    engine = create_engine(settings.database_url)
    item = (await ReferenceRepository(engine).provider_instruments("binance_usdm"))[0]
    now = SystemClock().now()
    candles = await CandleRepository(engine).for_analysis(
        item.provider_id, item.instrument.id, timeframe, now, limit
    )
    await engine.dispose()
    series = CandleSeries.of(candles)
    start = time.perf_counter()
    indicators = compute_indicators(series)
    middle = time.perf_counter()
    patterns = detect_patterns(series)
    end = time.perf_counter()
    print(f"{timeframe.value}: {len(series)} real candles, continuous={series.is_continuous}")
    print(f"indicators {(middle - start) * 1000:.0f} ms, patterns {(end - middle) * 1000:.0f} ms")
    last = {k: round(float(v[-1]), 3) for k, v in indicators.items() if k in ("rsi", "atr", "adx")}
    print("latest", last)
    for name, count in sorted(Counter(p.pattern_type for p in patterns).items()):
        share = sum(p.pattern_type == name and p.status == "invalidated" for p in patterns) / count
        print(f"  {name:20} {count:5}  invalidated {share:.0%}")

    def key(p: DetectedPattern) -> tuple[object, ...]:
        return (p.detected_at, p.pattern_type, p.formed_at, p.direction, str(p.price_level))

    failures = 0
    for cut in np.linspace(len(series) // 3, len(series) - 1, 6, dtype=int).tolist():
        moment = series.close_time[cut - 1]
        partial = sorted(
            (k for p in detect_patterns(series.upto(cut)) if (k := p.as_known_at(moment))), key=key
        )
        full = sorted((k for p in patterns if (k := p.as_known_at(moment))), key=key)
        failures += partial != full
        partial_values = compute_indicators(series.upto(cut))
        failures += any(
            not np.array_equal(values, indicators[name][:cut], equal_nan=True)
            for name, values in partial_values.items()
        )
    print("look-ahead failures on real data:", failures)


if __name__ == "__main__":
    asyncio.run(run(Timeframe(sys.argv[1]), int(sys.argv[2])))
