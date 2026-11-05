"""A no-edge baseline: the next candles rebuilt from this market's own recent candles.

Blocks of consecutive real candles are drawn at random, kept as shapes relative to their own
open, and chained from the last close. The paths move the way this market has moved lately,
with no view on direction. Adapted from the Time Machine in day-trader-skill (MIT).

A model forecast tells Claude something only where it differs from this baseline.
"""

from dataclasses import asdict, dataclass
from typing import Any, Final

import numpy as np

from trading_intel.forecasting.paths import SampledPaths
from trading_intel.technical_analysis.series import CandleSeries

SOURCE: Final = "time_machine"
VERSION: Final = "1"


@dataclass(frozen=True)
class TimeMachineParameters:
    lookback: int = 1440  # 60 days of 1H candles.
    block: int = 2  # Consecutive candles drawn together, so short-term follow-through survives.
    paths: int = 10_000
    seed: int = 19

    def as_json(self) -> dict[str, Any]:
        return {"version": VERSION, **asdict(self)}


def time_machine(
    series: CandleSeries, horizon: int, parameters: TimeMachineParameters | None = None
) -> SampledPaths:
    """Resampled paths from the last `lookback` candles of the series. Seeded, so repeatable."""
    chosen = parameters or TimeMachineParameters()
    if horizon < 1:
        raise ValueError("the horizon must be at least one candle")
    if len(series) < chosen.lookback or chosen.lookback <= chosen.block:
        raise ValueError(f"the baseline needs {chosen.lookback} candles, got {len(series)}")
    recent = series.window(len(series) - chosen.lookback, len(series))
    shapes = np.stack(
        [recent.high / recent.open, recent.low / recent.open, recent.close / recent.open], axis=1
    )
    rng = np.random.default_rng(chosen.seed)
    blocks = -(-horizon // chosen.block)
    starts = rng.integers(0, chosen.lookback - chosen.block + 1, size=(chosen.paths, blocks))
    index = (starts[:, :, None] + np.arange(chosen.block)).reshape(chosen.paths, -1)[:, :horizon]
    drawn = shapes[index]
    last_close = float(series.close[-1])
    closes = last_close * np.cumprod(drawn[..., 2], axis=1)
    opens = np.concatenate([np.full((chosen.paths, 1), last_close), closes[:, :-1]], axis=1)
    candles = np.stack([opens, opens * drawn[..., 0], opens * drawn[..., 1], closes], axis=-1)
    return SampledPaths(
        source=SOURCE,
        timeframe=series.timeframe,
        as_of=series.close_time[-1],
        last_close=last_close,
        candles=candles,
    )
