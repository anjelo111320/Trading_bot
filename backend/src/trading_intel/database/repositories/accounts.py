"""The owner account and the audit log."""

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


@dataclass(frozen=True)
class User:
    id: UUID
    email: str
    password_hash: str
    role: str


class UserRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def by_email(self, email: str) -> User | None:
        return await self._one("lower(email) = lower(:value)", email)

    async def by_id(self, user_id: UUID) -> User | None:
        return await self._one("id = :value", user_id)

    async def _one(self, condition: str, value: object) -> User | None:
        query = text(
            f"""SELECT id, email, password_hash, role FROM users
                WHERE is_active AND {condition}"""  # noqa: S608
        )
        async with self._engine.connect() as connection:
            row = (await connection.execute(query, {"value": value})).mappings().one_or_none()
        return User(**row) if row else None

    async def count(self) -> int:
        async with self._engine.connect() as connection:
            return int((await connection.execute(text("SELECT count(*) FROM users"))).scalar_one())

    async def create_owner(self, email: str, password_hash: str) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                text("INSERT INTO users (email, password_hash) VALUES (:email, :hash)"),
                {"email": email, "hash": password_hash},
            )


class AuditRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def record(
        self,
        actor: str,
        action: str,
        object_type: str,
        *,
        object_id: str | None = None,
        after: dict[str, Any] | None = None,
        request_id: str | None = None,
        ip_address: str | None = None,
    ) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    """INSERT INTO audit_log (actor, action, object_type, object_id, after,
                         request_id, ip_address)
                       VALUES (:actor, :action, :object_type, :object_id, CAST(:after AS jsonb),
                         :request_id, CAST(:ip AS inet))"""
                ),
                {
                    "actor": actor,
                    "action": action,
                    "object_type": object_type,
                    "object_id": object_id,
                    "after": json.dumps(after) if after is not None else None,
                    "request_id": request_id,
                    "ip": ip_address,
                },
            )
