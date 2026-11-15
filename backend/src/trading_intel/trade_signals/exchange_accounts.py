"""The Binance accounts the money plan trades: demo trading's test funds (D048) and the owner's
real USDⓈ-M futures wallet (D060). The quant worker and the dashboard's API both name them here.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal

from trading_intel.database.repositories.signals import (
    EXCHANGE_DEMO_ACCOUNT,
    EXCHANGE_DEMO_BUDGET,
    EXCHANGE_DEMO_MODE,
    EXCHANGE_LIVE_ACCOUNT,
    EXCHANGE_LIVE_MODE,
)
from trading_intel.risk_management.models import RiskProfile
from trading_intel.trade_signals.portfolio import EXCHANGE_DEMO_PROFILE, EXCHANGE_LIVE_PROFILE


@dataclass(frozen=True)
class ExchangeKind:
    venue: Literal["demo", "live"]
    name: str
    mode: str
    profile: RiskProfile
    # Demo trading trades a fixed budget of its test funds. On the real account the whole
    # futures wallet is the bot's, as the owner funds it.
    budget: Decimal | None

    @property
    def live(self) -> bool:
        return self.venue == "live"

    @property
    def starts_on(self) -> bool:
        """Whether the account trades before the owner first sets its switch: demo trading
        does (D064), the real account does not until it is armed (D060)."""
        return not self.live


DEMO: Final = ExchangeKind(
    "demo", EXCHANGE_DEMO_ACCOUNT, EXCHANGE_DEMO_MODE, EXCHANGE_DEMO_PROFILE, EXCHANGE_DEMO_BUDGET
)
LIVE: Final = ExchangeKind(
    "live", EXCHANGE_LIVE_ACCOUNT, EXCHANGE_LIVE_MODE, EXCHANGE_LIVE_PROFILE, None
)
