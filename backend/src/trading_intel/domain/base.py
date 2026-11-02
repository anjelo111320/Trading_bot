"""Base model for domain contracts."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class DomainModel(BaseModel):
    """Immutable and strict. Strict mode is what makes a float price an error."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class DataOrigin(StrEnum):
    LIVE = "live"
    BACKFILL = "backfill"
    SYNTHETIC = "synthetic"
