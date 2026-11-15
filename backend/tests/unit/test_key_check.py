"""The real account's key check (D060), against a fake HTTP transport. Nothing reaches Binance."""

from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest

from trading_intel.core.errors import ConfigurationError
from trading_intel.execution.binance_futures import BinanceError, HmacSigner, sign
from trading_intel.execution.key_check import KeyChecker, judge

# Binance's answer for a key made with only Enable Reading and Enable Futures ticked.
FUTURES_ONLY = {
    "ipRestrict": True,
    "createTime": 1_800_000_000_000,
    "enableReading": True,
    "enableWithdrawals": False,
    "enableInternalTransfer": False,
    "enableMargin": False,
    "enableFutures": True,
    "permitsUniversalTransfer": False,
    "enableVanillaOptions": False,
    "enableFixApiTrade": False,
    "enableFixReadOnly": False,
    "enableSpotAndMarginTrading": False,
    "enablePortfolioMarginTrading": False,
}


def test_a_key_that_reads_and_trades_futures_only_is_accepted() -> None:
    check = judge(FUTURES_ONLY)
    assert check.ok and check.ip_restricted and check.problems() == []


@pytest.mark.parametrize(
    ("permission", "meaning"),
    [
        ("enableWithdrawals", "withdraw"),
        ("enableInternalTransfer", "move funds between accounts"),
        ("permitsUniversalTransfer", "move funds between wallets"),
        ("enableSpotAndMarginTrading", "trade spot and margin"),
        ("enableMargin", "use margin loans"),
        ("enableVanillaOptions", "trade options"),
        ("enablePortfolioMarginTrading", "trade portfolio margin"),
    ],
)
def test_a_key_that_can_move_money_or_trade_elsewhere_is_refused(
    permission: str, meaning: str
) -> None:
    check = judge({**FUTURES_ONLY, permission: True})
    assert not check.ok and check.refused == (permission,)
    assert check.problems() == [f"the key can {meaning}: turn it off"]


def test_a_permission_binance_adds_later_is_refused_until_it_is_known() -> None:
    assert judge({**FUTURES_ONLY, "enableSomethingNew": True}).refused == ("enableSomethingNew",)


def test_a_key_that_cannot_trade_futures_is_refused() -> None:
    check = judge({**FUTURES_ONLY, "enableFutures": False, "ipRestrict": False})
    assert not check.ok and check.missing == ("enableFutures",) and not check.ip_restricted
    assert check.problems() == ["the key cannot trade USDⓈ-M futures: turn it on"]


async def test_the_check_asks_binances_permissions_endpoint_only_with_a_signed_request() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=FUTURES_ONLY)

    client = httpx.AsyncClient(
        base_url="https://api.binance.com", transport=httpx.MockTransport(handler)
    )
    checker = KeyChecker("live-key", HmacSigner("live-secret"), client, now_ms=lambda: 1_234)
    assert (await checker.check()).ok
    [request] = seen
    assert request.url.host == "api.binance.com"
    assert request.url.path == "/sapi/v1/account/apiRestrictions"
    assert request.headers["X-MBX-APIKEY"] == "live-key"
    query = urlsplit(str(request.url)).query
    values = dict(parse_qsl(query))
    assert values["timestamp"] == "1234"
    unsigned = query.rsplit("&signature=", 1)[0]
    assert values["signature"] == sign("live-secret", unsigned)


async def test_an_error_from_binance_is_raised_not_taken_as_a_pass() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401, json={"code": -2015, "msg": "Invalid API-key, IP, or permissions."}
        )

    client = httpx.AsyncClient(
        base_url="https://api.binance.com", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(BinanceError, match="-2015"):
        await KeyChecker("k", HmacSigner("s"), client).check()


@pytest.mark.parametrize("host", ["https://fapi.binance.com", "https://example.com"])
def test_the_check_cannot_be_pointed_at_another_host(host: str) -> None:
    with pytest.raises(ConfigurationError):
        KeyChecker("k", HmacSigner("s"), httpx.AsyncClient(base_url=host))
