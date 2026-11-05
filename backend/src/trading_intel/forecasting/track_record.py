"""How resolved forecasts have scored so far, for the model and for the baseline.

The status is what Claude is told about the model's reliability. It stays "too few
forecasts" until enough have resolved, and turns "better than baseline" only when both the
direction score and the distribution score favour the model with 95% confidence.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Any, Final, Literal

import numpy as np

from trading_intel.forecasting.scoring import MEASURES, Score

MINIMUM_FORECASTS: Final = 100
BUCKET_EDGES: Final = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
RESAMPLES: Final = 2000
SEED: Final = 11

Status = Literal[
    "too few forecasts", "better than baseline", "worse than baseline", "no difference shown"
]


@dataclass(frozen=True)
class Bucket:
    low: float
    high: float
    count: int
    mean_forecast: float | None  # Average share of paths ending higher.
    observed: float | None  # How often the price actually ended higher.


@dataclass(frozen=True)
class SourceRecord:
    brier: float
    close_crps_pct: float
    inside_band: dict[str, float]  # Near 0.8 when the 10th to 90th percentile band is honest.
    reliability: tuple[Bucket, ...]
    close_level_counts: tuple[int, ...]  # Tenths. Roughly flat when the forecast is calibrated.


@dataclass(frozen=True)
class Interval:
    mean: float
    low: float
    high: float


@dataclass(frozen=True)
class TrackRecord:
    count: int
    status: Status
    model: SourceRecord | None = None
    baseline: SourceRecord | None = None
    brier_difference: Interval | None = None  # Model minus baseline. Below zero favours the model.
    crps_difference: Interval | None = None

    def facts(self) -> dict[str, Any]:
        """The short form Claude reads."""
        if self.model is None or self.baseline is None:
            return {"resolved": self.count, "status": self.status}
        return {
            "resolved": self.count,
            "status": self.status,
            "brier": {
                "model": round(self.model.brier, 3),
                "baseline": round(self.baseline.brier, 3),
            },
            "close_crps_pct": {
                "model": round(self.model.close_crps_pct, 3),
                "baseline": round(self.baseline.close_crps_pct, 3),
            },
        }


def track_record(pairs: Sequence[tuple[Score, Score]]) -> TrackRecord:
    """Pairs of (model, baseline) scores for the same forecasts."""
    if not pairs:
        return TrackRecord(count=0, status="too few forecasts")
    model = [m for m, _ in pairs]
    baseline = [b for _, b in pairs]
    brier = _interval([m.brier - b.brier for m, b in pairs])
    crps = _interval([m.close_crps_pct - b.close_crps_pct for m, b in pairs])
    status: Status
    if len(pairs) < MINIMUM_FORECASTS:
        status = "too few forecasts"
    elif brier.high < 0 and crps.high < 0:
        status = "better than baseline"
    elif brier.low > 0 or crps.low > 0:
        status = "worse than baseline"
    else:
        status = "no difference shown"
    return TrackRecord(
        count=len(pairs),
        status=status,
        model=_record(model),
        baseline=_record(baseline),
        brier_difference=brier,
        crps_difference=crps,
    )


def _record(scores: Sequence[Score]) -> SourceRecord:
    levels = np.array([s.levels["close"] for s in scores])
    counts = np.histogram(levels, bins=10, range=(0.0, 1.0))[0]
    return SourceRecord(
        brier=float(np.mean([s.brier for s in scores])),
        close_crps_pct=float(np.mean([s.close_crps_pct for s in scores])),
        inside_band={m: float(np.mean([s.inside_band[m] for s in scores])) for m in MEASURES},
        reliability=tuple(
            _bucket(scores, low, high, last=high == BUCKET_EDGES[-1])
            for low, high in pairwise(BUCKET_EDGES)
        ),
        close_level_counts=tuple(int(c) for c in counts),
    )


def _bucket(scores: Sequence[Score], low: float, high: float, *, last: bool) -> Bucket:
    inside = [
        s for s in scores if low <= s.share_higher < high or (last and s.share_higher == high)
    ]
    if not inside:
        return Bucket(low, high, 0, None, None)
    return Bucket(
        low=low,
        high=high,
        count=len(inside),
        mean_forecast=float(np.mean([s.share_higher for s in inside])),
        observed=float(np.mean([s.ended_higher for s in inside])),
    )


def _interval(differences: Sequence[float]) -> Interval:
    """Mean with a 95% paired bootstrap interval. Seeded, so a report is reproducible.

    It assumes forecasts are independent. Overlapping horizons make the interval too narrow.
    """
    values = np.asarray(differences)
    rng = np.random.default_rng(SEED)
    means = values[rng.integers(0, len(values), size=(RESAMPLES, len(values)))].mean(axis=1)
    return Interval(
        mean=float(values.mean()),
        low=float(np.percentile(means, 2.5)),
        high=float(np.percentile(means, 97.5)),
    )
