"""What the real account's key may do, asked of Binance before the bot uses it (D060).

Binance lets every key read every wallet: no setting limits reading to futures. So the bot
refuses a key that can do more than read and trade USDⓈ-M futures. It must not withdraw,
transfer between wallets or accounts, or trade spot, margin or options. Then even a stolen
key with its private key could not move money out of Spot or Funding.

This is the only request the bot sends outside futures, to Binance's endpoint that reports a
key's permissions. It reads no balance. The bot itself reads only futures (`FUTURES_PATHS`).
"""

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlencode

import httpx

from trading_intel.core.errors import ConfigurationError
from trading_intel.execution.binance_futures import (
    TIMEOUT_SECONDS,
    BinanceError,
    BinanceFuturesGateway,
    BinanceHaltError,
    Signer,
)

# Fixed in code, so no setting can point the key anywhere else.
RESTRICTIONS_HOST: Final = "https://api.binance.com"
RESTRICTIONS_PATH: Final = "/sapi/v1/account/apiRestrictions"
RECV_WINDOW_MS: Final = 10_000
# Permissions the key may hold. Any other one that is on, including ones Binance adds later,
# refuses the key.
ALLOWED: Final = frozenset({"enableReading", "enableFutures", "ipRestrict", "enableFixReadOnly"})
REQUIRED: Final = ("enableFutures",)
# What a refused permission means, for the owner.
MEANING: Final[dict[str, str]] = {
    "enableWithdrawals": "withdraw",
    "enableInternalTransfer": "move funds between accounts",
    "permitsUniversalTransfer": "move funds between wallets",
    "enableSpotAndMarginTrading": "trade spot and margin",
    "enableMargin": "use margin loans",
    "enableVanillaOptions": "trade options",
    "enablePortfolioMarginTrading": "trade portfolio margin",
    "enableFixApiTrade": "trade through FIX",
    "enableFutures": "trade USDⓈ-M futures",
}


@dataclass(frozen=True)
class KeyCheck:
    """Binance's answer about one key. `refused` must be turned off and `missing` on."""

    refused: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    ip_restricted: bool = False

    @property
    def ok(self) -> bool:
        return not self.refused and not self.missing

    def problems(self) -> list[str]:
        """Plain sentences for the dashboard and the terminal."""
        found = [f"the key can {MEANING.get(name, name)}: turn it off" for name in self.refused]
        found += [f"the key cannot {MEANING.get(name, name)}: turn it on" for name in self.missing]
        return found


def judge(restrictions: Mapping[str, object]) -> KeyCheck:
    """Refuse every permission beyond reading and futures, and require futures."""
    refused = sorted(
        name for name, value in restrictions.items() if value is True and name not in ALLOWED
    )
    missing = [name for name in REQUIRED if restrictions.get(name) is not True]
    return KeyCheck(tuple(refused), tuple(missing), restrictions.get("ipRestrict") is True)


class KeyChecker:
    def __init__(
        self,
        api_key: str,
        signer: Signer,
        client: httpx.AsyncClient | None = None,
        now_ms: Callable[[], int] = lambda: int(time.time() * 1000),
    ) -> None:
        if not api_key:
            raise ConfigurationError("the Binance live API key is not set")
        self._client = client or httpx.AsyncClient(
            base_url=RESTRICTIONS_HOST, timeout=TIMEOUT_SECONDS
        )
        if str(self._client.base_url).rstrip("/") != RESTRICTIONS_HOST:
            raise ConfigurationError(f"the key check may only ask {RESTRICTIONS_HOST} (D060)")
        self._key = api_key
        self._signer = signer
        self._now_ms = now_ms

    async def aclose(self) -> None:
        await self._client.aclose()

    async def check(self) -> KeyCheck:
        """Ask Binance what the key may do. Raises BinanceError if Binance does not answer."""
        query = urlencode({"recvWindow": RECV_WINDOW_MS, "timestamp": self._now_ms()})
        query = f"{query}&{urlencode({'signature': self._signer(query)})}"
        response = await self._client.get(
            f"{RESTRICTIONS_PATH}?{query}", headers={"X-MBX-APIKEY": self._key}
        )
        try:
            body = response.json()
        except ValueError:
            body = None
        if response.status_code >= 400 or not isinstance(body, dict):
            code = body.get("code") if isinstance(body, dict) else None
            message = str(body.get("msg")) if isinstance(body, dict) else response.text[:200]
            error = (
                BinanceHaltError if response.status_code in (403, 418, 429, 451) else BinanceError
            )
            raise error(response.status_code, code, message)
        return judge(body)


@dataclass(frozen=True)
class AccountCheck:
    """The real account's key and settings, as the hourly check found them (D060). Any problem
    stops new trades; open trades keep their stops and targets."""

    problems: tuple[str, ...] = ()
    ip_restricted: bool = False


def _reason(error: Exception) -> str:
    return (error.message if isinstance(error, BinanceError) else type(error).__name__)[:160]


async def check_account(gateway: BinanceFuturesGateway, keys: KeyChecker) -> AccountCheck:
    """Everything the real account needs before the bot may open a trade on it: a key that can
    only read and trade futures, one position per coin, and figures in USDT alone."""
    try:
        await gateway.sync_clock()
        key = await keys.check()
    except (BinanceError, httpx.HTTPError) as error:
        return AccountCheck((f"the key could not be checked with Binance: {_reason(error)}",))
    problems = key.problems()
    try:
        if not await gateway.one_way_mode():
            problems.append("the account holds positions in hedge mode: switch it to one-way")
        if await gateway.multi_assets_mode():
            problems.append("multi-assets mode is on: switch it off, so figures are USDT alone")
    except (BinanceError, httpx.HTTPError) as error:
        problems.append(f"the futures account could not be read: {_reason(error)}")
    return AccountCheck(tuple(problems), key.ip_restricted)
