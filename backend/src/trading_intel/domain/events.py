"""The envelope carried by every internal and client-facing event."""

from typing import Any
from uuid import UUID

from trading_intel.core.clock import UtcDatetime
from trading_intel.domain.base import DataOrigin, DomainModel


class EventEnvelope(DomainModel):
    event_id: UUID
    event_type: str
    schema_version: int
    occurred_at: UtcDatetime
    seq: int
    data_origin: DataOrigin
    payload: dict[str, Any]
