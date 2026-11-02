"""Results of pattern detection. A label means a written rule fired, nothing more."""

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from typing import Any, Final

RULE_VERSION: Final = "1"


class Direction(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


@dataclass(frozen=True)
class DetectedPattern:
    pattern_type: str
    direction: Direction
    formed_at: datetime
    detected_at: datetime
    price_level: float | None = None
    zone_low: float | None = None
    zone_high: float | None = None
    invalidated_at: datetime | None = None
    strength: float = 0.0
    evidence: dict[str, Any] = field(default_factory=dict)
    rule_version: str = RULE_VERSION

    @property
    def status(self) -> str:
        return "invalidated" if self.invalidated_at else "confirmed"

    def invalidated(self, at: datetime) -> DetectedPattern:
        return replace(self, invalidated_at=at)

    def as_known_at(self, moment: datetime) -> DetectedPattern | None:
        """What could be known at a moment. Later invalidation is not yet visible."""
        if self.detected_at > moment:
            return None
        if self.invalidated_at is not None and self.invalidated_at > moment:
            return replace(self, invalidated_at=None)
        return self


def clamp_score(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 2)
