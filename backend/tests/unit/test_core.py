import io
import json
import re
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
import structlog
from pydantic import BaseModel, ValidationError

import trading_intel
from tests.conftest import TEST_SECRET, make_settings
from trading_intel.core.clock import (
    FixedClock,
    UtcDatetime,
    ensure_utc,
    from_epoch_ms,
    to_epoch_ms,
)
from trading_intel.core.errors import ConfigurationError
from trading_intel.core.logging import REDACTED, SecretFilter
from trading_intel.core.settings import Settings, TradingMode, load_settings


class Stamped(BaseModel):
    at: UtcDatetime


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValidationError, match="naive datetime rejected"):
        Stamped(at=datetime(2026, 1, 1))  # noqa: DTZ001


def test_other_timezones_become_utc() -> None:
    plus_five = timezone(timedelta(hours=5))
    assert ensure_utc(datetime(2026, 1, 1, 5, tzinfo=plus_five)) == datetime(2026, 1, 1, tzinfo=UTC)
    assert ensure_utc(datetime(2026, 1, 1, 5, tzinfo=plus_five)).tzinfo is UTC


def test_epoch_conversion_round_trips_to_the_millisecond() -> None:
    raw = 1_786_492_799_999
    assert to_epoch_ms(from_epoch_ms(raw)) == raw


def test_fixed_clock_moves_only_when_told() -> None:
    clock = FixedClock(datetime(2026, 1, 1, tzinfo=UTC))
    assert clock.now() == clock.now()
    clock.advance(10)
    assert clock.now() == datetime(2026, 1, 1, 0, 0, 10, tzinfo=UTC)
    assert clock.monotonic() == 10


def test_sleep_moves_wall_clock_but_not_monotonic_time() -> None:
    clock = FixedClock(datetime(2026, 1, 1, tzinfo=UTC))
    clock.jump_wall_clock(1800)
    assert clock.now() == datetime(2026, 1, 1, 0, 30, tzinfo=UTC)
    assert clock.monotonic() == 0


def test_trading_mode_has_exactly_one_member() -> None:
    assert list(TradingMode) == [TradingMode.PAPER]


def test_settings_have_no_trading_mode_field() -> None:
    assert not any("trading_mode" in name for name in Settings.model_fields)


def test_the_only_exchange_credentials_are_for_demo_trading_and_reading_news() -> None:
    """D016, amended by D048 and D032: keys exist for Binance demo trading, whose host is fixed,
    and one read-only key for Binance's announcement stream, added by the owner on 2026-11-11."""
    secret = ("key", "secret")
    exchange = [
        name
        for name in Settings.model_fields
        if name.startswith("binance") and any(word in name for word in secret)
    ]
    assert exchange == [
        "binance_read_api_key",
        "binance_read_api_secret",
        "binance_demo_api_key",
        "binance_demo_api_secret",
        "binance_demo_private_key_file",
    ]
    assert not any("demo" in name and "url" in name for name in Settings.model_fields), (
        "the demo order host must not be configurable"
    )


def test_the_read_only_key_reaches_only_the_announcement_stream() -> None:
    """The main-account key is read by the ingestor and passed to one module, nothing else."""
    package = Path(trading_intel.__file__).parent
    users = sorted(
        str(path.relative_to(package))
        for path in package.rglob("*.py")
        if "binance_read_api" in path.read_text()
    )
    assert users == ["core/settings.py", "entrypoints/ingestor.py"]
    module = (package / "news_intelligence" / "binance_announcements.py").read_text()
    paths = set(re.findall(r"/(?:sapi|api|fapi|dapi|papi)/[\w/]*", module))
    assert paths == {"/sapi/v1/account/apiRestrictions", "/sapi/wss"}, (
        "the read-only key may only check its own permissions and open the announcement stream"
    )


def test_missing_required_setting_gives_a_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in ("APP_SECRET_KEY", "DATABASE_URL", "REDIS_URL"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ConfigurationError, match="database_url"):
        load_settings()


def test_short_secret_key_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_settings(app_secret_key="short")


def test_cors_origins_split_from_environment_text() -> None:
    assert make_settings(cors_origins="http://a.test, http://b.test").cors_origins == [
        "http://a.test",
        "http://b.test",
    ]


def test_secret_filter_removes_configured_value_and_sensitive_keys() -> None:
    log_filter = SecretFilter([TEST_SECRET])
    event = {
        "event": f"connecting with {TEST_SECRET}",
        "api_key": "abc",
        "nested": {"password": "hunter2", "note": TEST_SECRET},
        "items": [TEST_SECRET],
    }
    result = log_filter(None, "info", event)
    rendered = json.dumps(result)
    assert TEST_SECRET not in rendered
    assert "hunter2" not in rendered
    assert result["api_key"] == REDACTED


def test_log_output_contains_no_configured_secret() -> None:
    settings = make_settings()
    stream = io.StringIO()
    structlog.configure(
        processors=[SecretFilter(settings.secret_values()), structlog.processors.JSONRenderer()],
        logger_factory=structlog.PrintLoggerFactory(file=stream),
    )
    structlog.get_logger().info("database", url=settings.database_url.get_secret_value())
    structlog.reset_defaults()
    assert "local_dev_only" not in stream.getvalue()
    assert REDACTED in stream.getvalue()
