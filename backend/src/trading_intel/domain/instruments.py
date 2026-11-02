"""Instruments and the exchange rules that apply to them."""

from decimal import Decimal
from enum import StrEnum
from typing import Any

from trading_intel.domain.base import DomainModel


class InstrumentType(StrEnum):
    SPOT = "spot"
    LINEAR_PERPETUAL = "linear_perpetual"


class Instrument(DomainModel):
    id: int
    symbol: str
    instrument_type: InstrumentType
    base_asset: str
    quote_asset: str
    settle_asset: str
    contract_multiplier: Decimal = Decimal(1)


class InstrumentRules(DomainModel):
    status: str
    tick_size: Decimal
    lot_step: Decimal
    min_qty: Decimal
    max_qty: Decimal
    market_max_qty: Decimal | None = None
    min_notional: Decimal
    max_notional: Decimal | None = None
    initial_margin_fraction: Decimal | None = None
    maintenance_margin_fraction: Decimal | None = None
    raw: dict[str, Any]

    def same_terms_as(self, other: InstrumentRules) -> bool:
        """Compare the rules themselves. The raw payload changes for unrelated reasons."""
        return self.model_dump(exclude={"raw"}) == other.model_dump(exclude={"raw"})
