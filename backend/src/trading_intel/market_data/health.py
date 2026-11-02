"""Feed health. Time comes from the injected Clock, so states are tested without sleeping."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from trading_intel.core.clock import Clock


class FeedState(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    DISCONNECTED = "DISCONNECTED"
    RECOVERING = "RECOVERING"


@dataclass(frozen=True)
class Thresholds:
    """Seconds. All configurable."""

    kline_degraded: float = 10
    kline_stale: float = 30
    book_degraded: float = 5
    book_stale: float = 30
    silent_stream: float = 30


@dataclass(frozen=True)
class FeedStatus:
    state: FeedState
    reasons: tuple[str, ...]
    last_event_at: datetime | None
    lag_seconds: float | None
    open_gaps: int
    clock_skew_ms: float | None

    @property
    def usable(self) -> bool:
        """Whether later phases may act on this feed."""
        return self.state is FeedState.HEALTHY


class FeedHealth:
    """Watches every expected stream, because a live connection can carry a dead stream."""

    def __init__(
        self,
        clock: Clock,
        routes: Iterable[str],
        expected_streams: Iterable[str],
        thresholds: Thresholds | None = None,
    ) -> None:
        self._clock = clock
        self._thresholds = thresholds or Thresholds()
        self._links: dict[str, bool] = dict.fromkeys(routes, False)
        self._link_reason: dict[str, str] = {}
        self._linked_at: dict[str, datetime] = {}
        self._expected = tuple(expected_streams)
        self._seen: dict[str, datetime] = {}
        self._last_event: datetime | None = None
        self._recovering: str | None = None
        self.open_gaps = 0
        self.clock_skew_ms: float | None = None

    def link_up(self, route: str) -> None:
        self._links[route] = True
        self._linked_at[route] = self._clock.now()
        self._link_reason.pop(route, None)

    def link_down(self, route: str, reason: str) -> None:
        self._links[route] = False
        self._link_reason[route] = reason

    def saw(self, stream: str) -> None:
        now = self._clock.now()
        self._seen[stream] = now
        self._last_event = now

    def begin_recovery(self, reason: str) -> None:
        self._recovering = reason

    def end_recovery(self) -> None:
        self._recovering = None

    def status(self) -> FeedStatus:
        state, reasons = self._assess()
        lag = None
        if self._last_event is not None:
            lag = (self._clock.now() - self._last_event).total_seconds()
        return FeedStatus(
            state=state,
            reasons=reasons,
            last_event_at=self._last_event,
            lag_seconds=lag,
            open_gaps=self.open_gaps,
            clock_skew_ms=self.clock_skew_ms,
        )

    def _assess(self) -> tuple[FeedState, tuple[str, ...]]:
        if self._recovering:
            return FeedState.RECOVERING, (self._recovering,)
        down = [route for route, up in self._links.items() if not up]
        if down:
            reasons = tuple(
                f"{route}: {self._link_reason.get(route, 'not connected')}" for route in down
            )
            return FeedState.DISCONNECTED, reasons
        stale, degraded = self._stream_ages()
        if stale:
            return FeedState.STALE, tuple(stale)
        if degraded:
            return FeedState.DEGRADED, tuple(degraded)
        return FeedState.HEALTHY, ()

    def _stream_ages(self) -> tuple[list[str], list[str]]:
        now = self._clock.now()
        started = min(self._linked_at.values(), default=now)
        stale: list[str] = []
        degraded: list[str] = []
        limits = self._thresholds
        for stream in self._expected:
            seen = self._seen.get(stream)
            if seen is None:
                if (now - started).total_seconds() > limits.silent_stream:
                    stale.append(f"{stream}: silent since connecting")
                continue
            age = (now - seen).total_seconds()
            is_book = stream.startswith("book")
            stale_after = limits.book_stale if is_book else limits.kline_stale
            degraded_after = limits.book_degraded if is_book else limits.kline_degraded
            if age > stale_after:
                stale.append(f"{stream}: no data for {age:.0f}s")
            elif age > degraded_after:
                degraded.append(f"{stream}: no data for {age:.0f}s")
        return stale, degraded
