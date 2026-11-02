"""Alembic environment. Always connects as the migration role."""

import asyncio

from alembic import context
from sqlalchemy import MetaData
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from trading_intel.core.settings import load_settings

# Constraint names are written in the SQL itself, so names stay deterministic.
target_metadata = MetaData(
    naming_convention={
        "ix": "%(table_name)s_%(column_0_name)s_idx",
        "uq": "%(table_name)s_%(column_0_name)s_key",
        "ck": "%(table_name)s_%(constraint_name)s",
        "fk": "%(table_name)s_%(column_0_name)s_fkey",
        "pk": "%(table_name)s_pkey",
    }
)


def run_on(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    url = load_settings().migration_database_url.get_secret_value()
    engine = create_async_engine(url)
    async with engine.connect() as connection:
        await connection.run_sync(run_on)
        await connection.commit()
    await engine.dispose()


asyncio.run(run_online())
