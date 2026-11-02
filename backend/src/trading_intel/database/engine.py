"""Database engines. Each process connects with the least-privileged role it needs."""

from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def create_engine(url: SecretStr, *, pool_size: int = 5) -> AsyncEngine:
    return create_async_engine(
        url.get_secret_value(),
        pool_size=pool_size,
        max_overflow=2,
        pool_pre_ping=True,
    )


async def ping(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
