"""Setup quality: an evidence checklist, not a probability.

Technical quality, news alignment, data reliability and probability stay separate.
Weights are starting points. They need out-of-sample evidence before meaning more.
"""

from dataclasses import dataclass
from typing import Final

WEIGHTS: Final = {
    "timeframe_alignment": 25,
    "market_structure": 20,
    "momentum": 15,
    "volume": 10,
    "entry_quality": 10,
    "reward_risk": 10,
    "volatility": 10,
}


@dataclass(frozen=True)
class SetupEvidence:
    """Each input is 0 to 1. `conflicts` counts evidence against the trade."""

    timeframe_alignment: float
    market_structure: float
    momentum: float
    volume: float
    entry_quality: float
    reward_risk: float
    volatility: float
    conflicts: int = 0


@dataclass(frozen=True)
class SetupQuality:
    score: float
    components: dict[str, float]
    conflicts: int


CONFLICT_PENALTY: Final = 10.0


def score_setup(evidence: SetupEvidence) -> SetupQuality:
    components: dict[str, float] = {}
    for name, weight in WEIGHTS.items():
        value = getattr(evidence, name)
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{name} must be between 0 and 1")
        components[name] = round(value * weight, 2)
    total = sum(components.values()) - evidence.conflicts * CONFLICT_PENALTY
    return SetupQuality(round(max(total, 0.0), 2), components, evidence.conflicts)
