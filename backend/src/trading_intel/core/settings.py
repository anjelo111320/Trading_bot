"""Typed settings. Trading mode is deliberately not one of them."""

from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Final, Literal

from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from trading_intel.core.errors import ConfigurationError


class TradingMode(StrEnum):
    """Paper is the only member, so no code path can represent live trading (D016)."""

    PAPER = "paper"


TRADING_MODE: Final = TradingMode.PAPER

REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPOSITORY_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"
    app_secret_key: SecretStr = Field(min_length=32)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    cors_origins: Annotated[list[str], NoDecode] = []

    database_url: SecretStr
    ingest_database_url: SecretStr
    migration_database_url: SecretStr
    redis_url: SecretStr

    binance_spot_rest_url: str = "https://api.binance.com"
    binance_spot_ws_url: str = "wss://stream.binance.com:9443"
    binance_usdm_rest_url: str = "https://fapi.binance.com"
    binance_usdm_ws_url: str = "wss://fstream.binance.com"

    anthropic_api_key: SecretStr = SecretStr("")

    owner_email: str = ""
    owner_password: SecretStr = SecretStr("")
    session_lifetime_hours: int = Field(default=24, gt=0)

    max_risk_per_trade: Decimal = Decimal("0.01")
    max_daily_loss: Decimal = Decimal("0.03")
    min_reward_risk: Decimal = Decimal("2.0")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    def secret_values(self) -> tuple[str, ...]:
        """Every configured secret, so the log filter can remove them."""
        secrets = (
            self.app_secret_key,
            self.database_url,
            self.ingest_database_url,
            self.migration_database_url,
            self.redis_url,
            self.owner_password,
            self.anthropic_api_key,
        )
        return tuple(value for s in secrets if (value := s.get_secret_value()))


def load_settings() -> Settings:
    """Load settings, turning a missing value into one clear startup error."""
    try:
        return Settings()
    except ValidationError as error:
        problems = ", ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in error.errors()
        )
        raise ConfigurationError(f"invalid settings: {problems}") from error
