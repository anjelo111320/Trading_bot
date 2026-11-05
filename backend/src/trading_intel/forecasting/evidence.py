"""The forecast section of Claude's context, labelled as unvalidated model output.

Distances are in ATR of the setup timeframe from the last close, the unit pattern facts use
(D035). Levels are referred to by catalogue ID, so the forecast adds no price of its own (D009).
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Final

from trading_intel.domain.candles import Timeframe
from trading_intel.forecasting.summary import BAND, Measure, PathSummary, reach_share
from trading_intel.forecasting.track_record import TrackRecord

LABEL: Final = "unvalidated model forecast"


def forecast_facts(
    model: PathSummary,
    baseline: PathSummary,
    *,
    model_name: str,
    timeframe: Timeframe,
    as_of: datetime,
    last_close: float,
    atr: float,
    record: TrackRecord,
    levels: Sequence[tuple[str, float]] = (),
) -> dict[str, Any]:
    """`levels` holds (catalogue ID, price) pairs, such as the candidate's stop and targets."""
    if not atr > 0:
        raise ValueError("ATR must be positive")

    def spread(summary: PathSummary) -> dict[str, Any]:
        def band(measure: Measure) -> dict[str, float]:
            return {f"p{p}": round((summary.at(measure, p) - last_close) / atr, 2) for p in BAND}

        return {
            "share_ending_higher": round(summary.share_higher, 2),
            "highest_atr": band("high"),
            "lowest_atr": band("low"),
            "close_atr": band("close"),
        }

    return {
        "label": LABEL,
        "model": model_name,
        "as_of": as_of.isoformat(),
        "timeframe": timeframe.value,
        "horizon_candles": model.horizon,
        "paths": {"model": model.count, "baseline": baseline.count},
        "forecast": spread(model),
        "baseline": spread(baseline),
        "levels": [
            {
                "id": level_id,
                "reached_share": {
                    "model": round(reach_share(model, price, last_close), 2),
                    "baseline": round(reach_share(baseline, price, last_close), 2),
                },
            }
            for level_id, price in levels
        ],
        "track_record": record.facts(),
    }
