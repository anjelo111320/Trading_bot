"""Which strategy runs at which close, and that stale closes never trade (D042)."""

from datetime import UTC, datetime, timedelta
from typing import Any

from tests.unit.test_backtesting import INSTRUMENT
from trading_intel.core.clock import FixedClock
from trading_intel.domain.candles import Timeframe
from trading_intel.domain.signals import Action
from trading_intel.entrypoints.quant_worker import TradingLoop
from trading_intel.trade_signals.service import SignalOutcome

NOW = datetime(2026, 11, 6, 17, 0, 5, tzinfo=UTC)
PROVIDER = 2


class Recorder:
    """Stands in for the signal service, paper service and accounts, and notes each call."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def evaluate_pattern(self, *args: Any) -> SignalOutcome:
        self.calls.append("pattern")
        return SignalOutcome(Action.NO_TRADE, None, False, ())

    async def evaluate_trend(self, *args: Any) -> SignalOutcome:
        self.calls.append("trend")
        return SignalOutcome(Action.NO_TRADE, None, False, ())

    async def trail_stops(self, *args: Any) -> int:
        self.calls.append("trail")
        return 0

    async def sync(self, *args: Any) -> None:
        self.calls.append("sync")

    async def ensure_account(self, email: str) -> object:
        return object()


def loop(recorder: Recorder) -> TradingLoop:
    return TradingLoop(
        recorder,  # type: ignore[arg-type]
        recorder,  # type: ignore[arg-type]
        recorder,  # type: ignore[arg-type]
        "owner@example.test",
        PROVIDER,
        {INSTRUMENT.id: INSTRUMENT},
        FixedClock(NOW),
    )


async def closed(timeframe: Timeframe, age: timedelta) -> list[str]:
    recorder = Recorder()
    await loop(recorder).on_closed(PROVIDER, INSTRUMENT.id, timeframe, NOW - age)
    return recorder.calls


async def test_a_fresh_1h_close_runs_the_pattern_strategy() -> None:
    assert await closed(Timeframe.H1, timedelta(seconds=5)) == ["pattern"]


async def test_a_fresh_daily_close_trails_stops_then_runs_the_trend_strategy() -> None:
    assert await closed(Timeframe.D1, timedelta(seconds=5)) == ["trail", "trend"]


async def test_a_stale_close_never_trades() -> None:
    """A backlog or a wake from sleep replays old closes. They must not become signals."""
    assert await closed(Timeframe.H1, timedelta(minutes=16)) == []
    assert await closed(Timeframe.D1, timedelta(hours=2)) == []


async def test_minute_closes_always_replay_paper_fills() -> None:
    assert await closed(Timeframe.M1, timedelta(hours=5)) == ["sync"]


async def test_other_timeframes_and_coins_do_nothing() -> None:
    assert await closed(Timeframe.M15, timedelta(seconds=5)) == []
    recorder = Recorder()
    await loop(recorder).on_closed(PROVIDER, 999, Timeframe.H1, NOW)
    assert recorder.calls == []


class Failing(Recorder):
    async def evaluate_trend(self, *args: Any) -> SignalOutcome:
        raise ValueError("a bad signal")


async def test_one_failing_signal_does_not_stop_the_loop() -> None:
    """Regression: one bad daily signal stopped paper trading for every coin (2026-11-07)."""
    recorder = Failing()
    await loop(recorder).on_closed(
        PROVIDER, INSTRUMENT.id, Timeframe.D1, NOW - timedelta(seconds=5)
    )
    assert recorder.calls == ["trail"]
