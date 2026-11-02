from datetime import UTC, datetime, timedelta
from decimal import Decimal

from trading_intel.core.clock import FixedClock
from trading_intel.domain.market import MarkPrice, OpenInterest, TopOfBook
from trading_intel.market_data.health import FeedHealth, FeedState
from trading_intel.market_data.recovery import SleepDetector
from trading_intel.market_data.snapshots import MinuteAggregator

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def feed() -> tuple[FeedHealth, FixedClock]:
    clock = FixedClock(NOW)
    health = FeedHealth(clock, ["spot"], ["kline:1:1m", "book:1"])
    health.link_up("spot")
    health.saw("kline:1:1m")
    health.saw("book:1")
    return health, clock


def test_fresh_streams_are_healthy_and_usable() -> None:
    health, _ = feed()
    status = health.status()
    assert status.state is FeedState.HEALTHY
    assert status.usable
    assert status.reasons == ()


def test_a_feed_that_never_connected_is_disconnected() -> None:
    health = FeedHealth(FixedClock(NOW), ["spot"], ["book:1"])
    assert health.status().state is FeedState.DISCONNECTED


def test_old_kline_data_degrades_then_goes_stale() -> None:
    health, clock = feed()
    clock.advance(11)
    health.saw("book:1")
    assert health.status().state is FeedState.DEGRADED
    assert not health.status().usable
    clock.advance(20)
    health.saw("book:1")
    status = health.status()
    assert status.state is FeedState.STALE
    assert "kline:1:1m" in status.reasons[0]


def test_book_data_degrades_sooner_than_klines() -> None:
    health, clock = feed()
    clock.advance(6)
    health.saw("kline:1:1m")
    assert health.status().state is FeedState.DEGRADED


def test_link_loss_is_disconnected_and_reports_why() -> None:
    health, _ = feed()
    health.link_down("spot", "connection closed: 1006")
    status = health.status()
    assert status.state is FeedState.DISCONNECTED
    assert "1006" in status.reasons[0]


def test_silent_stream_on_a_live_connection_is_flagged_within_thirty_seconds() -> None:
    """Regression: the legacy futures path connected, then silently dropped klines."""
    clock = FixedClock(NOW)
    health = FeedHealth(clock, ["market"], ["kline:1:1m", "book:1"])
    health.link_up("market")
    for _ in range(31):
        clock.advance(1)
        health.saw("book:1")
    status = health.status()
    assert status.state is FeedState.STALE
    assert "silent since connecting" in status.reasons[0]


def test_recovering_outranks_everything_and_blocks_use() -> None:
    health, _ = feed()
    health.begin_recovery("computer slept")
    status = health.status()
    assert status.state is FeedState.RECOVERING
    assert not status.usable
    health.end_recovery()
    assert health.status().usable


def test_status_exposes_lag_gaps_and_skew() -> None:
    health, clock = feed()
    health.open_gaps = 2
    health.clock_skew_ms = 12.5
    clock.advance(3)
    status = health.status()
    assert status.lag_seconds == 3
    assert status.open_gaps == 2
    assert status.clock_skew_ms == 12.5
    assert status.last_event_at == NOW


def book(at: datetime, bid: str, ask: str, instrument: int = 1) -> TopOfBook:
    return TopOfBook(
        provider_id=1,
        instrument_id=instrument,
        bid_price=Decimal(bid),
        bid_quantity=Decimal(1),
        ask_price=Decimal(ask),
        ask_quantity=Decimal(1),
        received_at=at,
    )


def test_minute_statistics_are_exact() -> None:
    aggregator = MinuteAggregator(1)
    aggregator.add_book(book(NOW, "100", "100.1"))
    aggregator.add_book(book(NOW + timedelta(seconds=10), "100", "100.3"))
    aggregator.add_book(book(NOW + timedelta(seconds=20), "100", "100.2"))
    [row] = aggregator.flush(NOW + timedelta(minutes=1))
    assert row.minute_start == NOW
    assert row.spread_min == Decimal("0.1")
    assert row.spread_max == Decimal("0.3")
    assert row.spread_mean == Decimal("0.2")
    assert row.spread_last == Decimal("0.2")
    assert row.sample_count == 3
    assert row.best_bid == Decimal(100)
    assert row.best_ask == Decimal("100.2")


def test_a_minute_is_held_until_it_has_finished() -> None:
    aggregator = MinuteAggregator(1)
    aggregator.add_book(book(NOW + timedelta(seconds=59), "100", "101"))
    assert aggregator.flush(NOW + timedelta(seconds=59, milliseconds=999)) == []
    assert len(aggregator.flush(NOW + timedelta(minutes=1))) == 1
    assert aggregator.flush(NOW + timedelta(minutes=2)) == []


def test_samples_land_in_their_own_minute() -> None:
    aggregator = MinuteAggregator(1)
    aggregator.add_book(book(NOW + timedelta(seconds=59), "100", "101"))
    aggregator.add_book(book(NOW + timedelta(seconds=60), "100", "102"))
    rows = aggregator.flush(NOW + timedelta(minutes=2))
    assert [row.spread_last for row in rows] == [Decimal(1), Decimal(2)]


def test_an_empty_minute_produces_no_row() -> None:
    aggregator = MinuteAggregator(1)
    aggregator.add_book(book(NOW, "100", "101"))
    rows = aggregator.flush(NOW + timedelta(minutes=5))
    assert [row.minute_start for row in rows] == [NOW]


def test_crossed_book_is_counted_and_kept_out_of_the_statistics() -> None:
    aggregator = MinuteAggregator(1)
    aggregator.add_book(book(NOW, "100", "100.5"))
    aggregator.add_book(book(NOW, "101", "100.5"))
    [row] = aggregator.flush(NOW + timedelta(minutes=1))
    assert row.sample_count == 1
    assert row.crossed_book_count == 1
    assert row.spread_max == Decimal("0.5")


def test_instruments_stay_separate() -> None:
    aggregator = MinuteAggregator(1)
    aggregator.add_book(book(NOW, "100", "101", instrument=1))
    aggregator.add_book(book(NOW, "100", "102", instrument=2))
    rows = aggregator.flush(NOW + timedelta(minutes=1))
    assert {row.instrument_id: row.spread_last for row in rows} == {
        1: Decimal(1),
        2: Decimal(2),
    }


def test_mark_price_and_open_interest_join_the_same_row() -> None:
    aggregator = MinuteAggregator(1)
    aggregator.add_mark(
        MarkPrice(
            provider_id=1,
            instrument_id=1,
            mark_price=Decimal(100),
            index_price=Decimal(99),
            event_time=NOW,
            received_at=NOW,
        )
    )
    aggregator.add_open_interest(
        OpenInterest(
            provider_id=1,
            instrument_id=1,
            open_interest=Decimal(500),
            event_time=NOW,
            received_at=NOW,
        )
    )
    [row] = aggregator.flush(NOW + timedelta(minutes=1))
    assert row.mark_price == Decimal(100)
    assert row.index_price == Decimal(99)
    assert row.open_interest == Decimal(500)
    assert row.sample_count == 0


def test_normal_running_is_not_mistaken_for_sleep() -> None:
    clock = FixedClock(NOW)
    detector = SleepDetector(clock)
    clock.advance(3600)
    assert detector.check() is None


def test_a_wall_clock_jump_is_detected_as_sleep() -> None:
    clock = FixedClock(NOW)
    detector = SleepDetector(clock)
    clock.jump_wall_clock(1800)
    downtime = detector.check()
    assert downtime is not None
    assert downtime.start == NOW
    assert downtime.seconds == 1800
    assert detector.check() is None


def test_a_short_pause_is_ignored() -> None:
    clock = FixedClock(NOW)
    detector = SleepDetector(clock)
    clock.jump_wall_clock(10)
    assert detector.check() is None
