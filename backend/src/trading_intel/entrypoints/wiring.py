"""Build providers and services for the process entry points."""

import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Final

from trading_intel.core.clock import Clock
from trading_intel.core.errors import ConfigurationError
from trading_intel.core.settings import REPOSITORY_ROOT, Settings
from trading_intel.data_providers.base import MarketDataProvider
from trading_intel.data_providers.binance.provider import SPOT, USDM, BinanceProvider, Venue
from trading_intel.data_providers.binance.rest import BinanceRestClient
from trading_intel.data_providers.synthetic.provider import SyntheticProvider
from trading_intel.database.repositories.reference import ProviderInstrument

BINANCE_SPOT: Final = "binance_spot"
BINANCE_USDM: Final = "binance_usdm"
SYNTHETIC: Final = "synthetic"

# The first data Binance holds, verified 2026-11-02.
EARLIEST: Final[dict[tuple[str, str], datetime]] = {
    (BINANCE_SPOT, "BTCUSDT"): datetime(2017, 8, 17, tzinfo=UTC),
    (BINANCE_SPOT, "ETHUSDT"): datetime(2017, 8, 17, tzinfo=UTC),
    (BINANCE_USDM, "BTCUSDT"): datetime(2019, 9, 8, tzinfo=UTC),
    (BINANCE_USDM, "ETHUSDT"): datetime(2019, 11, 27, tzinfo=UTC),
}


def git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            cwd=REPOSITORY_ROOT,
            check=True,
        )
    except OSError, subprocess.CalledProcessError:
        return "unknown"
    return result.stdout.strip()


def build_provider(
    code: str,
    settings: Settings,
    clock: Clock,
    listed: Sequence[ProviderInstrument],
) -> MarketDataProvider:
    provider_id = listed[0].provider_id
    if code == SYNTHETIC:
        return SyntheticProvider(provider_id, clock)
    venues: dict[str, tuple[Venue, str, str]] = {
        BINANCE_SPOT: (SPOT, settings.binance_spot_rest_url, settings.binance_spot_ws_url),
        BINANCE_USDM: (USDM, settings.binance_usdm_rest_url, settings.binance_usdm_ws_url),
    }
    if code not in venues:
        raise ConfigurationError(f"unknown provider {code}")
    venue, rest_url, ws_url = venues[code]
    rest = BinanceRestClient(rest_url, venue.allowed_paths, venue.rest_cap_per_minute, clock)
    symbols = {item.instrument.id: item.provider_symbol for item in listed}
    return BinanceProvider(venue, provider_id, symbols, rest, ws_url, clock)
