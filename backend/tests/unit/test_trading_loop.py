"""Which strategy runs at which close, and that stale closes never trade (D042, D044, D045)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from tests.unit.test_backtesting import INSTRUMENT
from trading_intel.core.clock import FixedClock
from trading_intel.domain.candles import Timeframe
from trading_intel.domain.signals import Action
from trading_intel.entrypoints.quant_worker import NewsReadings, TradingLoop
from trading_intel.news_intelligence.reading import NewsReading
from trading_intel.trade_signals.service import SignalOutcome

NOW = datetime(2026, 11, 6, 17, 0, 5, tzinfo=UTC)
PROVIDER = 2


class Recorder:
    """Stands in for the signal service, paper service and accounts, and notes each call."""

    def __init__(self, decided: bool = False) -> None:
        self.calls: list[str] = []
        self.already_decided = decided

    async def evaluate(self, *args: Any, instant: bool = False) -> SignalOutcome:
        self.calls.append(f"baseline instant={instant}")
        return SignalOutcome(Action.NO_TRADE, None, False, ())

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

    async def ensure_account(self, email: str, name: str = "Paper", *args: Any) -> object:
        self.calls.append(f"account {name}")
        return Account()

    async def decided(self, *args: Any) -> bool:
        return self.already_decided

    async def plan_setups(self, provider_id: int, instruments: list[Any], at: datetime) -> Any:
        self.calls.append(f"plan setups for {len(instruments)} coin")
        return [], []

    async def run_plan(self, *args: Any) -> list[SignalOutcome]:
        self.calls.append("plan")
        return []


class Account:
    id = "portfolio"


def loop(recorder: Recorder) -> TradingLoop:
    async def sleep(seconds: float) -> None:
        recorder.calls.append(f"wait {seconds:g}s")

    return TradingLoop(
        recorder,  # type: ignore[arg-type]
        recorder,  # type: ignore[arg-type]
        recorder,  # type: ignore[arg-type]
        "owner@example.test",
        PROVIDER,
        {INSTRUMENT.id: INSTRUMENT},
        FixedClock(NOW),
        sleep,
    )


async def closed(timeframe: Timeframe, age: timedelta) -> list[str]:
    recorder = Recorder()
    await loop(recorder).on_closed(PROVIDER, INSTRUMENT.id, timeframe, NOW - age)
    return recorder.calls


async def test_a_fresh_1h_close_runs_the_pattern_strategy() -> None:
    assert await closed(Timeframe.H1, timedelta(seconds=15)) == ["account Paper", "pattern"]


async def test_a_fresh_daily_close_trails_stops_then_runs_the_trend_strategy() -> None:
    assert await closed(Timeframe.D1, timedelta(seconds=15)) == [
        "account Paper",
        "trail",
        "trend",
    ]


async def test_a_fresh_15m_close_runs_the_demo_bot_then_the_money_plan() -> None:
    assert await closed(Timeframe.M15, timedelta(seconds=15)) == [
        "account Demo",
        "baseline instant=True",
        "account Portfolio",
        "plan setups for 1 coin",
        "plan",
    ]


async def test_the_money_plan_runs_once_per_close_for_every_coin() -> None:
    recorder = Recorder()
    trading = loop(recorder)
    close = NOW - timedelta(seconds=15)
    await trading.on_closed(PROVIDER, INSTRUMENT.id, Timeframe.M15, close)
    await trading.on_closed(PROVIDER, INSTRUMENT.id, Timeframe.M15, close)
    assert recorder.calls.count("plan") == 1
    assert recorder.calls.count("baseline instant=True") == 2


async def test_a_restart_never_repeats_a_decided_close() -> None:
    recorder = Recorder(decided=True)
    await loop(recorder).on_closed(
        PROVIDER, INSTRUMENT.id, Timeframe.M15, NOW - timedelta(seconds=15)
    )
    assert "plan" not in recorder.calls


async def test_a_stale_close_never_trades() -> None:
    """A backlog or a wake from sleep replays old closes. They must not become signals."""
    assert await closed(Timeframe.M15, timedelta(minutes=6)) == []
    assert await closed(Timeframe.H1, timedelta(minutes=16)) == []
    assert await closed(Timeframe.D1, timedelta(hours=2)) == []


async def test_minute_closes_always_replay_paper_fills() -> None:
    assert await closed(Timeframe.M1, timedelta(hours=5)) == ["sync"]


async def test_other_timeframes_and_coins_do_nothing() -> None:
    assert await closed(Timeframe.M5, timedelta(seconds=15)) == []
    assert await closed(Timeframe.H4, timedelta(seconds=15)) == []
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
        PROVIDER, INSTRUMENT.id, Timeframe.D1, NOW - timedelta(seconds=15)
    )
    assert recorder.calls == ["account Paper", "trail"]


async def test_a_just_closed_candle_waits_for_the_order_book_to_settle() -> None:
    """Regression: a decision two seconds after a close could read a book a minute old."""
    assert await closed(Timeframe.H1, timedelta(seconds=4)) == [
        "wait 6s",
        "account Paper",
        "pattern",
    ]


class FakeCandles:
    def __init__(self, close: str | None = "70123.4") -> None:
        self.close = close
        self.asked: list[tuple[Any, ...]] = []

    async def range(self, *args: Any) -> list[Any]:
        self.asked.append(args)
        return [] if self.close is None else [SimpleNamespace(close=Decimal(self.close))]


class FakeNews:
    def __init__(self) -> None:
        self.stored: list[tuple[Any, ...]] = []

    async def record_reading(self, *args: Any) -> bool:
        self.stored.append(args)
        return True


class FakeSignal:
    async def reading(self, instrument_id: int, at: datetime) -> NewsReading:
        return NewsReading(at, "bearish", Decimal("-1.8"), ())


FOUR_HOUR_CLOSE = datetime(2026, 11, 6, 15, 59, 59, 999000, tzinfo=UTC)


async def test_each_coins_news_reading_is_kept_at_4h_closes_only() -> None:
    """D055: the reading and the 15M close price at each 4H close, for the forward test."""
    candles, news = FakeCandles(), FakeNews()
    readings = NewsReadings(candles, news, FakeSignal())  # type: ignore[arg-type]
    await readings.record(PROVIDER, INSTRUMENT, FOUR_HOUR_CLOSE - timedelta(minutes=15))
    assert candles.asked == [] and news.stored == []
    await readings.record(PROVIDER, INSTRUMENT, FOUR_HOUR_CLOSE)
    opened = datetime(2026, 11, 6, 15, 45, tzinfo=UTC)
    assert candles.asked == [
        (PROVIDER, INSTRUMENT.id, Timeframe.M15, opened, opened + timedelta(minutes=15))
    ]
    [(instrument_id, at, price, reading)] = news.stored
    assert (instrument_id, at, price) == (INSTRUMENT.id, FOUR_HOUR_CLOSE, Decimal("70123.4"))
    assert reading.direction == "bearish"


async def test_no_close_price_means_no_reading() -> None:
    news = FakeNews()
    readings = NewsReadings(FakeCandles(None), news, FakeSignal())  # type: ignore[arg-type]
    await readings.record(PROVIDER, INSTRUMENT, FOUR_HOUR_CLOSE)
    assert news.stored == []


class FailingReadings:
    def __init__(self) -> None:
        self.calls = 0

    async def record(self, *args: Any) -> None:
        self.calls += 1
        raise RuntimeError("news store unreachable")


async def test_a_failing_news_reading_never_stops_the_15m_close() -> None:
    recorder, failing = Recorder(), FailingReadings()
    trading = loop(recorder)
    trading._news = failing  # type: ignore[assignment]
    await trading.on_closed(PROVIDER, INSTRUMENT.id, Timeframe.M15, NOW - timedelta(seconds=15))
    assert failing.calls == 1 and recorder.calls[-1] == "plan"
