"""Sleep detection. The platform runs on a computer that sleeps, so this is a normal path."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from trading_intel.core.clock import Clock

SLEEP_THRESHOLD_SECONDS = 30.0


@dataclass(frozen=True)
class Downtime:
    start: datetime
    end: datetime

    @property
    def seconds(self) -> float:
        return (self.end - self.start).total_seconds()


class SleepDetector:
    """Compares wall time with monotonic time, which stops while the computer sleeps."""

    def __init__(self, clock: Clock, threshold: float = SLEEP_THRESHOLD_SECONDS) -> None:
        self._clock = clock
        self._threshold = threshold
        self._wall = clock.now()
        self._monotonic = clock.monotonic()

    def check(self) -> Downtime | None:
        wall, monotonic = self._clock.now(), self._clock.monotonic()
        wall_elapsed = (wall - self._wall).total_seconds()
        slept = wall_elapsed - (monotonic - self._monotonic)
        previous = self._wall
        self._wall, self._monotonic = wall, monotonic
        if slept > self._threshold:
            return Downtime(previous, previous + timedelta(seconds=wall_elapsed))
        return None
