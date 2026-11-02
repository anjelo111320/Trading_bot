"""Providers and instruments."""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from trading_intel.core.errors import NotFoundError
from trading_intel.domain.instruments import Instrument, InstrumentType


@dataclass(frozen=True)
class ProviderInstrument:
    provider_id: int
    provider_code: str
    provider_symbol: str
    instrument: Instrument


class ReferenceRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def provider_id(self, code: str) -> int:
        async with self._engine.connect() as connection:
            result = await connection.execute(
                text("SELECT id FROM providers WHERE code = :code"), {"code": code}
            )
            value = result.scalar_one_or_none()
        if value is None:
            raise NotFoundError(f"unknown provider {code}")
        return int(value)

    async def provider_instruments(self, code: str | None = None) -> list[ProviderInstrument]:
        query = """
            SELECT p.id AS provider_id, p.code, pi.provider_symbol, i.id, i.canonical_symbol,
                   i.instrument_type, i.base_asset, i.quote_asset, i.settle_asset,
                   i.contract_multiplier
            FROM provider_instruments pi
            JOIN providers p ON p.id = pi.provider_id
            JOIN instruments i ON i.id = pi.instrument_id
            WHERE pi.is_active AND i.is_active AND (CAST(:code AS text) IS NULL OR p.code = :code)
            ORDER BY p.id, i.id
        """
        async with self._engine.connect() as connection:
            rows = (await connection.execute(text(query), {"code": code})).mappings().all()
        return [
            ProviderInstrument(
                provider_id=row["provider_id"],
                provider_code=row["code"],
                provider_symbol=row["provider_symbol"],
                instrument=Instrument(
                    id=row["id"],
                    symbol=row["canonical_symbol"],
                    instrument_type=InstrumentType(row["instrument_type"]),
                    base_asset=row["base_asset"],
                    quote_asset=row["quote_asset"],
                    settle_asset=row["settle_asset"],
                    contract_multiplier=row["contract_multiplier"],
                ),
            )
            for row in rows
        ]
