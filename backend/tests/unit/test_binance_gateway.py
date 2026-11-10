"""The Binance demo gateway, against a fake HTTP transport. Nothing here reaches Binance."""

import base64
import stat
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from trading_intel.core.errors import ConfigurationError
from trading_intel.execution.binance_futures import (
    DEMO_REST_URL,
    BinanceError,
    BinanceFuturesGateway,
    BinanceHaltError,
    Ed25519Signer,
    HmacSigner,
    Signer,
    generate_key_file,
    sign,
    signer_for,
)

SERVER_MS = 1_800_000_000_000
LOCAL_MS = SERVER_MS - 2_000  # This computer runs two seconds behind Binance.

Handler = Callable[[httpx.Request], httpx.Response]


def params(request: httpx.Request) -> dict[str, str]:
    return dict(parse_qsl(urlsplit(str(request.url)).query))


def gateway(handler: Handler, signer: Signer | None = None) -> BinanceFuturesGateway:
    def routed(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/fapi/v1/time":
            return httpx.Response(200, json={"serverTime": SERVER_MS})
        return handler(request)

    client = httpx.AsyncClient(base_url=DEMO_REST_URL, transport=httpx.MockTransport(routed))
    chosen = signer or HmacSigner("demo-secret")
    return BinanceFuturesGateway("demo-key", chosen, client, now_ms=lambda: LOCAL_MS)


def test_the_signature_matches_binances_documented_example() -> None:
    # Binance's published example secret from its signing docs, not a real key.
    secret = "NhqPtmdSJYdKjVHjA7PZj4Mge3R5YNiP1e3UZjInClVN65XAbvqqM6A7H5fATj0j"  # gitleaks:allow
    query = (
        "symbol=LTCBTC&side=BUY&type=LIMIT&timeInForce=GTC&quantity=1&price=0.1"
        "&recvWindow=5000&timestamp=1499827319559"
    )
    assert sign(secret, query) == "c8db56825ae71d6d79447849e617115f4a920fa2acdcab2b053c4b2838bd6b71"


@pytest.mark.parametrize("host", ["https://fapi.binance.com", "https://api.binance.com"])
def test_any_host_but_demo_trading_is_refused(host: str) -> None:
    with pytest.raises(ConfigurationError, match="demo"):
        BinanceFuturesGateway("key", HmacSigner("secret"), httpx.AsyncClient(base_url=host))


def test_missing_keys_are_refused() -> None:
    with pytest.raises(ConfigurationError):
        BinanceFuturesGateway("", HmacSigner("secret"))
    with pytest.raises(ConfigurationError):
        HmacSigner("")


async def test_a_signed_request_carries_the_key_binances_time_and_a_valid_signature() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"orderId": 1, "executedQty": "0.010", "avgPrice": "100"})

    reply = await gateway(handler).market_order("BTCUSDT", "BUY", Decimal("0.0100"), "ati-x-entry")
    assert reply["executedQty"] == "0.010"
    [request] = seen
    assert request.method == "POST" and request.url.path == "/fapi/v1/order"
    assert request.headers["X-MBX-APIKEY"] == "demo-key"
    sent = params(request)
    assert sent["timestamp"] == str(SERVER_MS)
    assert sent["quantity"] == "0.01"  # Decimals are sent plainly, without trailing zeros.
    assert "reduceOnly" not in sent
    query = urlsplit(str(request.url)).query
    unsigned, signature = query.rsplit("&signature=", 1)
    assert signature == sign("demo-secret", unsigned)


async def test_the_stop_closes_the_whole_position_and_a_target_only_reduces_it() -> None:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(params(request))
        return httpx.Response(200, json={"algoId": len(seen)})

    exchange = gateway(handler)
    await exchange.algo_order("BTCUSDT", "SELL", "STOP_MARKET", Decimal("95.5"), "ati-x-stop")
    await exchange.algo_order(
        "BTCUSDT",
        "SELL",
        "TAKE_PROFIT_MARKET",
        Decimal("110"),
        "ati-x-tp1",
        quantity=Decimal("0.005"),
    )
    stop, target = seen
    assert stop["closePosition"] == "true" and "quantity" not in stop and "reduceOnly" not in stop
    assert target["reduceOnly"] == "true" and target["quantity"] == "0.005"
    for order in (stop, target):
        assert order["algoType"] == "CONDITIONAL"
        assert order["workingType"] == "MARK_PRICE"
        assert order["priceProtect"] == "true"


async def test_a_setting_already_in_place_is_not_an_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"code": -4046, "msg": "No need to change margin type."})

    await gateway(handler).use_isolated("BTCUSDT")


async def test_a_clock_error_resyncs_and_retries_once() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(params(request)["timestamp"])
        if len(calls) == 1:
            return httpx.Response(400, json={"code": -1021, "msg": "Timestamp ahead"})
        return httpx.Response(200, json={"totalMarginBalance": "5000"})

    assert (await gateway(handler).account())["totalMarginBalance"] == "5000"
    assert len(calls) == 2


async def test_refusals_and_bans_are_raised_never_retried() -> None:
    calls: list[int] = []

    def refused(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(400, json={"code": -2019, "msg": "Margin is insufficient."})

    with pytest.raises(BinanceError) as caught:
        await gateway(refused).market_order("BTCUSDT", "BUY", Decimal(1), "ati-x-entry")
    assert caught.value.binance_code == -2019
    assert len(calls) == 1

    def limited(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"code": -1003, "msg": "Too many requests"})

    with pytest.raises(BinanceHaltError):
        await gateway(limited).account()


async def test_an_ed25519_signature_is_base64_url_encoded_and_verifies() -> None:
    private = Ed25519PrivateKey.generate()
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"totalMarginBalance": "5000"})

    await gateway(handler, Ed25519Signer(private)).account()
    query = urlsplit(str(seen[0].url)).query
    unsigned, encoded = query.rsplit("&signature=", 1)
    assert "+" not in encoded and "/" not in encoded, "base64 must be URL-encoded"
    signature = base64.b64decode(dict(parse_qsl(query))["signature"])
    private.public_key().verify(signature, unsigned.encode())  # Raises if it does not match.


def test_keygen_writes_a_private_key_only_this_user_can_read(tmp_path: Path) -> None:
    path = tmp_path / "keys" / "demo.pem"
    public = generate_key_file(path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    loaded = serialization.load_pem_public_key(public.encode())
    assert isinstance(loaded, Ed25519PublicKey)
    assert public.startswith("-----BEGIN PUBLIC KEY-----")
    signature = base64.b64decode(Ed25519Signer.from_file(path)("a=1&timestamp=2"))
    loaded.verify(signature, b"a=1&timestamp=2")
    with pytest.raises(ConfigurationError, match="already exists"):
        generate_key_file(path)


def test_the_key_file_is_preferred_and_the_secret_is_the_fallback(tmp_path: Path) -> None:
    missing = tmp_path / "none.pem"
    assert isinstance(signer_for("secret", missing), HmacSigner)
    with pytest.raises(ConfigurationError):
        signer_for("", missing)
    path = tmp_path / "demo.pem"
    generate_key_file(path)
    assert isinstance(signer_for("secret", path), Ed25519Signer)
    other = tmp_path / "other.pem"
    other.write_text("not a key")
    with pytest.raises(ValueError):
        Ed25519Signer.from_file(other)
