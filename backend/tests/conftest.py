"""Shared fixtures. Secrets here are test-only values."""

import pytest

from trading_intel.core.settings import Settings

TEST_SECRET = "test-secret-key-that-is-long-enough-000000"


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "test",
        "app_secret_key": TEST_SECRET,
        "database_url": "postgresql+asyncpg://ati_app:local_dev_only@127.0.0.1:55432/trading_test",
        "ingest_database_url": (
            "postgresql+asyncpg://ati_ingest:local_dev_only@127.0.0.1:55432/trading_test"
        ),
        "migration_database_url": (
            "postgresql+asyncpg://ati_migrator:local_dev_only@127.0.0.1:55432/trading_test"
        ),
        "redis_url": "redis://127.0.0.1:56379/1",
        "cors_origins": ["http://127.0.0.1:3000"],
        "_env_file": None,
    }
    return Settings(**{**values, **overrides})  # type: ignore[arg-type]


@pytest.fixture
def settings() -> Settings:
    return make_settings()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--live", action="store_true", help="run tests that call real providers")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--live"):
        return
    skip = pytest.mark.skip(reason="live provider test: use --live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
