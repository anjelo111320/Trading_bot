import asyncpg
import pytest

from tests.integration.support import SUPERUSER_URL, alembic

pytestmark = pytest.mark.integration


async def user_tables() -> set[str]:
    connection = await asyncpg.connect(SUPERUSER_URL)
    rows = await connection.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> "
        "'alembic_version'"
    )
    await connection.close()
    return {row["tablename"] for row in rows}


async def test_upgrade_and_downgrade_run_cleanly_on_an_empty_database() -> None:
    down = alembic("downgrade", "base")
    assert down.returncode == 0, down.stderr
    assert await user_tables() == set()

    up = alembic("upgrade", "head")
    assert up.returncode == 0, up.stderr

    down = alembic("downgrade", "base")
    assert down.returncode == 0, down.stderr
    assert await user_tables() == set()

    up = alembic("upgrade", "head")
    assert up.returncode == 0, up.stderr


async def test_migrations_create_objects_owned_by_the_migration_role() -> None:
    connection = await asyncpg.connect(SUPERUSER_URL)
    owner = await connection.fetchval(
        "SELECT pg_get_userbyid(typowner) FROM pg_type WHERE typname = 'timeframe_t'"
    )
    await connection.close()
    assert owner == "ati_migrator"
