"""Migrated test database, cleaned before each test."""

from collections.abc import AsyncIterator

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.conftest import make_settings
from tests.integration.support import SUPERUSER_URL, alembic
from trading_intel.database.engine import create_engine

CLEANED = (
    "market_candles",
    "market_candle_revisions",
    "market_gaps",
    "market_snapshots",
    "funding_rates",
    "liquidation_samples",
    "instrument_rule_snapshots",
    "ingest_runs",
    "system_events",
    "audit_log",
    "users",
    "news_articles",
)


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    result = alembic("upgrade", "head")
    assert result.returncode == 0, result.stderr


@pytest.fixture
async def clean_database() -> None:
    connection = await asyncpg.connect(SUPERUSER_URL)
    await connection.execute("SET session_replication_role = replica")
    await connection.execute(f"TRUNCATE {', '.join(CLEANED)}")
    await connection.close()


@pytest.fixture
async def ingest_engine(clean_database: None) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(make_settings().ingest_database_url)
    yield engine
    await engine.dispose()


@pytest.fixture
async def app_engine(clean_database: None) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(make_settings().database_url)
    yield engine
    await engine.dispose()
