"""Score one forecast against what happened next.

The model and the baseline are scored the same way, from their stored percentiles, so a
forecast is fixed before its outcome is known and the two can be compared fairly.
"""

from dataclasses import dataclass
from typing import Any, Final

import numpy as np

from trading_intel.forecasting.summary import BAND, GRID, Measure, PathSummary, quantile_level
from trading_intel.technical_analysis.series import CandleSeries

MEASURES: Final[tuple[Measure, ...]] = ("high", "low", "close")


@dataclass(frozen=True)
class Realized:
    high: float
    low: float
    close: float


def realized(after: CandleSeries, horizon: int) -> Realized:
    """What the first `horizon` candles after the forecast did."""
    if len(after) < horizon or not after.is_continuous:
        raise ValueError(f"an outcome needs {horizon} continuous candles, got {len(after)}")
    window = after.window(0, horizon)
    return Realized(
        high=float(window.high.max()), low=float(window.low.min()), close=float(window.close[-1])
    )


@dataclass(frozen=True)
class Score:
    share_higher: float
    ended_higher: bool
    brier: float  # Squared error of the share of paths ending higher. A coin flip scores 0.25.
    levels: dict[str, float]  # Where each realized value fell among the forecast's percentiles.
    inside_band: dict[str, bool]  # Whether it fell between the 10th and 90th percentiles.
    close_crps_pct: float  # Error of the whole close distribution, in percent of the last close.

    def as_json(self) -> dict[str, Any]:
        return {
            "share_higher": self.share_higher,
            "ended_higher": self.ended_higher,
            "brier": self.brier,
            "levels": self.levels,
            "inside_band": self.inside_band,
            "close_crps_pct": self.close_crps_pct,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Score:
        return cls(
            share_higher=float(data["share_higher"]),
            ended_higher=bool(data["ended_higher"]),
            brier=float(data["brier"]),
            levels={k: float(v) for k, v in data["levels"].items()},
            inside_band={k: bool(v) for k, v in data["inside_band"].items()},
            close_crps_pct=float(data["close_crps_pct"]),
        )


def crps(percentiles: tuple[float, ...], value: float) -> float:
    """Continuous ranked probability score from evenly spaced percentiles.

    Twice the mean quantile loss, which approximates the integral form. Lower is better, and
    a forecast that put everything on the realized value scores zero.
    """
    error = value - np.asarray(percentiles)
    levels = np.asarray(GRID)
    return float(2 * np.mean(np.where(error >= 0, levels * error, (levels - 1) * error)))


def score(summary: PathSummary, outcome: Realized, last_close: float) -> Score:
    values = {"high": outcome.high, "low": outcome.low, "close": outcome.close}
    ended_higher = outcome.close > last_close
    low_band, _, high_band = BAND
    return Score(
        share_higher=summary.share_higher,
        ended_higher=ended_higher,
        brier=(summary.share_higher - float(ended_higher)) ** 2,
        levels={m: quantile_level(summary.percentiles(m), values[m]) for m in MEASURES},
        inside_band={
            m: summary.at(m, low_band) <= values[m] <= summary.at(m, high_band) for m in MEASURES
        },
        close_crps_pct=100 * crps(summary.close, outcome.close) / last_close,
    )
