"""The design schema must load on PostgreSQL 18 with native uuidv7()."""

from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import asyncpg
import pytest

from tests.integration.support import SUPERUSER_URL

pytestmark = pytest.mark.integration

SCHEMA = Path(__file__).resolve().parents[3] / "docs" / "schema" / "schema-v0.sql"
SCRATCH = "schema_v0_check"


@pytest.fixture
async def database() -> AsyncIterator[asyncpg.Connection]:
    admin = await asyncpg.connect(SUPERUSER_URL)
    await admin.execute(f"DROP DATABASE IF EXISTS {SCRATCH}")
    await admin.execute(f"CREATE DATABASE {SCRATCH}")
    connection = await asyncpg.connect(SUPERUSER_URL.replace("trading_test", SCRATCH))
    await connection.execute(SCHEMA.read_text())
    yield connection
    await connection.close()
    await admin.execute(f"DROP DATABASE {SCRATCH}")
    await admin.close()


async def seed_account(connection: asyncpg.Connection) -> UUID:
    user = await connection.fetchval(
        "INSERT INTO users (email, password_hash) VALUES ('o@example.test', 'x') RETURNING id"
    )
    return await connection.fetchval(
        "INSERT INTO trading_accounts (user_id, name, base_currency, starting_balance) "
        "VALUES ($1, 'main', 'USDT', 10000) RETURNING id",
        user,
    )


async def test_schema_loads_with_native_uuidv7(database: asyncpg.Connection) -> None:
    tables = await database.fetchval("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")
    version = await database.fetchval("SHOW server_version")
    defaults = await database.fetchval(
        "SELECT column_default FROM information_schema.columns "
        "WHERE table_name = 'users' AND column_name = 'id'"
    )
    assert version.startswith("18.")
    assert tables == 47
    assert defaults == "uuidv7()"


async def test_a_non_paper_account_cannot_exist(database: asyncpg.Connection) -> None:
    user = await database.fetchval(
        "INSERT INTO users (email, password_hash) VALUES ('a@example.test', 'x') RETURNING id"
    )
    with pytest.raises(asyncpg.CheckViolationError):
        await database.execute(
            "INSERT INTO trading_accounts (user_id, name, mode, base_currency, starting_balance) "
            "VALUES ($1, 'bad', 'live', 'USDT', 1)",
            user,
        )


async def test_immutable_table_rejects_update_delete_and_truncate(
    database: asyncpg.Connection,
) -> None:
    await database.execute(
        "INSERT INTO audit_log (actor, action, object_type) VALUES ('t', 'a', 'o')"
    )
    for statement in (
        "UPDATE audit_log SET actor = 'x'",
        "DELETE FROM audit_log",
        "TRUNCATE audit_log",
    ):
        with pytest.raises(asyncpg.RestrictViolationError):
            await database.execute(statement)


@pytest.mark.parametrize(
    ("column", "value"),
    [("high", 99), ("low", 0), ("volume", -1)],
)
async def test_invalid_candle_is_rejected_by_the_database(
    database: asyncpg.Connection, column: str, value: int
) -> None:
    provider = await database.fetchval(
        "INSERT INTO providers (code, name, kind) VALUES ('p', 'P', 'market_data') RETURNING id"
    )
    instrument = await database.fetchval(
        "INSERT INTO instruments (canonical_symbol, instrument_type, base_asset, quote_asset, "
        "settle_asset) VALUES ('BTCUSDT', 'spot', 'BTC', 'USDT', 'USDT') RETURNING id"
    )
    values = {"high": 110, "low": 90, "volume": 1, column: value}
    with pytest.raises(asyncpg.CheckViolationError):
        await database.execute(
            "INSERT INTO market_candles (provider_id, instrument_id, timeframe, open_time, "
            "close_time, open, high, low, close, volume, quote_volume, trade_count, "
            "provider_open_time_raw, data_origin, received_at) VALUES "
            "($1, $2, '1m', now(), now() + interval '1 minute', 100, $3, $4, 105, $5, 1, 1, 1, "
            "'backfill', now())",
            provider,
            instrument,
            values["high"],
            values["low"],
            values["volume"],
        )


async def test_holdout_can_run_once_per_strategy(database: asyncpg.Connection) -> None:
    strategy = await database.fetchval(
        "INSERT INTO strategy_configurations (name, version, kind, parameters, content_hash) "
        "VALUES ('s', 1, 'rule_baseline', '{}', 'h') RETURNING id"
    )
    dataset = await database.fetchval(
        "INSERT INTO dataset_versions (name, manifest, content_sha256) VALUES ('d', '{}', 'h') "
        "RETURNING id"
    )
    insert = (
        "INSERT INTO backtest_runs (strategy_configuration_id, dataset_version_id, split, "
        "window_start, window_end, cost_model, git_sha, seed, trial_number) VALUES "
        "($1, $2, 'holdout', now(), now() + interval '1 day', '{}', 'g', 1, $3)"
    )
    await database.execute(insert, strategy, dataset, 1)
    with pytest.raises(asyncpg.UniqueViolationError):
        await database.execute(insert, strategy, dataset, 2)


async def test_a_buy_with_its_stop_above_entry_is_rejected(database: asyncpg.Connection) -> None:
    account = await seed_account(database)
    provider = await database.fetchval(
        "INSERT INTO providers (code, name, kind) VALUES ('p', 'P', 'market_data') RETURNING id"
    )
    instrument = await database.fetchval(
        "INSERT INTO instruments (canonical_symbol, instrument_type, base_asset, quote_asset, "
        "settle_asset) VALUES ('BTCUSDT', 'spot', 'BTC', 'USDT', 'USDT') RETURNING id"
    )
    strategy = await database.fetchval(
        "INSERT INTO strategy_configurations (name, version, kind, parameters, content_hash) "
        "VALUES ('s', 1, 'rule_baseline', '{}', 'h') RETURNING id"
    )
    with pytest.raises(asyncpg.CheckViolationError, match="rec_buy_stop_below_entry"):
        await database.execute(
            "INSERT INTO trade_recommendations (schema_version, strategy_configuration_id, "
            "account_id, provider_id, instrument_id, timeframe, action, entry_type, market_price, "
            "entry_price, stop_loss, dedupe_key, news_alignment, data_reliability_score, "
            "technical_explanation, fundamental_explanation, supporting_evidence, "
            "conflicting_evidence, invalidation_conditions, data_as_of, data_age_ms, expires_at) "
            "VALUES (1, $1, $2, $3, $4, '1h', 'BUY', 'LIMIT', 100, 100, 105, 'k', 'neutral', 90, "
            "'t', 'f', '[\"e\"]', '[]', '[\"i\"]', now(), 1, now() + interval '1 hour')",
            strategy,
            account,
            provider,
            instrument,
        )
