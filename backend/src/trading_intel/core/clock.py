"""UTC time. Business code reads the time through a Clock, so tests never sleep."""

import time
from datetime import UTC, datetime, timedelta
from typing import Annotated, Protocol

from pydantic import AfterValidator


def ensure_utc(value: datetime) -> datetime:
    """Convert an aware datetime to UTC. A naive datetime is an error."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("naive datetime rejected: all timestamps must be timezone-aware")
    return value.astimezone(UTC)


UtcDatetime = Annotated[datetime, AfterValidator(ensure_utc)]


def from_epoch_ms(value: int) -> datetime:
    """Convert a provider's epoch milliseconds to UTC."""
    return datetime.fromtimestamp(value / 1000, tz=UTC)


def to_epoch_ms(value: datetime) -> int:
    """Convert an aware datetime to epoch milliseconds without float rounding."""
    delta = ensure_utc(value) - datetime(1970, 1, 1, tzinfo=UTC)
    return delta // timedelta(milliseconds=1)


class Clock(Protocol):
    def now(self) -> datetime: ...

    def monotonic(self) -> float: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()


class FixedClock:
    """A clock that moves only when told to."""

    def __init__(self, start: datetime) -> None:
        self._now = ensure_utc(start)
        self._monotonic = 0.0

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._monotonic

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)
        self._monotonic += seconds

    def jump_wall_clock(self, seconds: float) -> None:
        """Move wall time only, which is how a computer's sleep looks from inside."""
        self._now += timedelta(seconds=seconds)
