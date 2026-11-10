"""Signed access to Binance USDⓈ-M Futures **demo trading**, the only exchange this code reaches.

The host is fixed. A client pointed anywhere else is refused, so real money cannot be reached
without changing this file (D048). Orders are never retried here: a retry could double a
position, so a failure goes back to the caller, which reconciles with Binance first.
"""

import base64
import hashlib
import hmac
import os
import time
from collections.abc import Callable, Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any, Final, Literal, Protocol
from urllib.parse import urlencode

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from trading_intel.core.errors import AppError, ConfigurationError

DEMO_REST_URL: Final = "https://demo-fapi.binance.com"
RECV_WINDOW_MS: Final = 5000
TIMEOUT_SECONDS: Final = 10.0
# Codes that mean the setting was already as asked. They are not failures.
ALREADY_SET: Final = frozenset({-4046, -4059})  # Margin type; position mode.
CLOCK_AHEAD: Final = -1021

Method = Literal["GET", "POST", "DELETE"]
OrderSide = Literal["BUY", "SELL"]
AlgoType = Literal["STOP_MARKET", "TAKE_PROFIT_MARKET"]


class BinanceError(AppError):
    """Binance refused a request. `binance_code` is Binance's own error number."""

    code = "binance_error"
    status_code = 502

    def __init__(self, http_status: int, binance_code: int | None, message: str) -> None:
        super().__init__(f"Binance {http_status} {binance_code}: {message}")
        self.http_status = http_status
        self.binance_code = binance_code


class BinanceHaltError(BinanceError):
    """Rate limit, IP ban, location block or WAF. Nothing more may be sent for a while."""

    code = "binance_halt"


def _text(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    return str(value)


def sign(secret: str, query: str) -> str:
    """HMAC SHA-256 of the query string, as Binance documents for HMAC keys."""
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()


class Signer(Protocol):
    def __call__(self, query: str) -> str: ...


class HmacSigner:
    """A system-generated key: Binance holds the secret too."""

    def __init__(self, secret: str) -> None:
        if not secret:
            raise ConfigurationError("the Binance demo secret is not set")
        self._secret = secret

    def __call__(self, query: str) -> str:
        return sign(self._secret, query)


class Ed25519Signer:
    """A self-generated key: the private key never leaves this computer, and Binance holds only
    its public half. The signature is the base64 Ed25519 signature of the query string, as
    Binance's own SDK sends it.
    """

    def __init__(self, private_key: Ed25519PrivateKey) -> None:
        self._key = private_key

    @classmethod
    def from_file(cls, path: Path) -> Ed25519Signer:
        if not path.is_file():
            raise ConfigurationError(f"no private key at {path}; run binance_demo keygen")
        loaded = serialization.load_pem_private_key(path.read_bytes(), password=None)
        if not isinstance(loaded, Ed25519PrivateKey):
            raise ConfigurationError(f"{path} is not an Ed25519 private key")
        return cls(loaded)

    def __call__(self, query: str) -> str:
        return base64.b64encode(self._key.sign(query.encode())).decode()


def generate_key_file(path: Path) -> str:
    """Write a new Ed25519 private key readable only by this user, and return its public key.

    An existing file is never replaced, because a key in use would stop working.
    """
    if path.exists():
        raise ConfigurationError(f"{path} already exists; delete it first to make a new key")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(pem)
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return public.decode()


def signer_for(secret: str, key_file: Path) -> Signer:
    """The self-generated Ed25519 key when its file exists, else the system-generated secret."""
    if key_file.is_file():
        return Ed25519Signer.from_file(key_file)
    if secret:
        return HmacSigner(secret)
    raise ConfigurationError("no Binance demo private key file or secret is set")


class BinanceFuturesGateway:
    def __init__(
        self,
        api_key: str,
        signer: Signer,
        client: httpx.AsyncClient | None = None,
        now_ms: Callable[[], int] = lambda: int(time.time() * 1000),
    ) -> None:
        if not api_key:
            raise ConfigurationError("the Binance demo API key is not set")
        self._client = client or httpx.AsyncClient(base_url=DEMO_REST_URL, timeout=TIMEOUT_SECONDS)
        if str(self._client.base_url).rstrip("/") != DEMO_REST_URL:
            raise ConfigurationError(
                f"only Binance demo trading at {DEMO_REST_URL} is allowed (D048)"
            )
        self._key = api_key
        self._signer = signer
        self._now_ms = now_ms
        self._offset_ms: int | None = None

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _send(self, method: Method, path: str, query: str, headers: Mapping[str, str]) -> Any:
        response = await self._client.request(
            method, f"{path}?{query}" if query else path, headers=headers
        )
        if response.status_code < 400:
            return response.json()
        try:
            body = response.json()
        except ValueError:
            body = {}
        code = body.get("code") if isinstance(body, dict) else None
        message = (
            str(body.get("msg", response.text[:200]))
            if isinstance(body, dict)
            else response.text[:200]
        )
        if response.status_code in (403, 418, 429, 451):
            raise BinanceHaltError(response.status_code, code, message)
        raise BinanceError(response.status_code, code, message)

    async def server_time(self) -> int:
        body = await self._send("GET", "/fapi/v1/time", "", {})
        return int(body["serverTime"])

    async def sync_clock(self) -> int:
        """Binance rejects a timestamp ahead of its clock, so requests carry its time."""
        before = self._now_ms()
        server = await self.server_time()
        self._offset_ms = server - (before + self._now_ms()) // 2
        return self._offset_ms

    async def _signed(
        self, method: Method, path: str, params: Mapping[str, object] | None = None
    ) -> Any:
        if self._offset_ms is None:
            await self.sync_clock()
        for attempt in (1, 2):
            values = {
                key: _text(value) for key, value in (params or {}).items() if value is not None
            }
            values["recvWindow"] = str(RECV_WINDOW_MS)
            values["timestamp"] = str(self._now_ms() + (self._offset_ms or 0))
            query = urlencode(values)
            # A base64 signature holds "+", "/" and "=", so it is URL-encoded like any value.
            query = f"{query}&{urlencode({'signature': self._signer(query)})}"
            try:
                return await self._send(method, path, query, {"X-MBX-APIKEY": self._key})
            except BinanceError as error:
                # Only a clock error is retried: Binance rejected it before acting on it.
                if error.binance_code != CLOCK_AHEAD or attempt == 2:
                    raise
                await self.sync_clock()
        raise AssertionError("unreachable")

    async def _setting(self, path: str, params: Mapping[str, object]) -> None:
        try:
            await self._signed("POST", path, params)
        except BinanceError as error:
            if error.binance_code not in ALREADY_SET:
                raise

    # Account and positions.

    async def account(self) -> dict[str, Any]:
        result: dict[str, Any] = await self._signed("GET", "/fapi/v3/account")
        return result

    async def positions(self) -> list[dict[str, Any]]:
        """Positions, and symbols with open orders, as Binance reports them."""
        result: list[dict[str, Any]] = await self._signed("GET", "/fapi/v3/positionRisk")
        return result

    async def one_way_mode(self) -> bool:
        body = await self._signed("GET", "/fapi/v1/positionSide/dual")
        return not body["dualSidePosition"]

    async def use_one_way_mode(self) -> None:
        """One position per coin, as the risk engine and the paper accounts assume."""
        await self._setting("/fapi/v1/positionSide/dual", {"dualSidePosition": False})

    async def use_isolated(self, symbol: str) -> None:
        await self._setting("/fapi/v1/marginType", {"symbol": symbol, "marginType": "ISOLATED"})

    async def set_leverage(self, symbol: str, leverage: int) -> None:
        await self._signed("POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": leverage})

    # Orders.

    async def market_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        client_id: str,
        *,
        reduce_only: bool = False,
    ) -> dict[str, Any]:
        result: dict[str, Any] = await self._signed(
            "POST",
            "/fapi/v1/order",
            {
                "symbol": symbol,
                "side": side,
                "type": "MARKET",
                "quantity": quantity,
                "reduceOnly": True if reduce_only else None,
                "newClientOrderId": client_id,
                "newOrderRespType": "RESULT",
            },
        )
        return result

    async def order(self, symbol: str, client_id: str) -> dict[str, Any]:
        result: dict[str, Any] = await self._signed(
            "GET", "/fapi/v1/order", {"symbol": symbol, "origClientOrderId": client_id}
        )
        return result

    async def algo_order(
        self,
        symbol: str,
        side: OrderSide,
        kind: AlgoType,
        trigger: Decimal,
        client_id: str,
        *,
        quantity: Decimal | None = None,
    ) -> dict[str, Any]:
        """A stop or take-profit held by Binance, on the mark price, with price protection.

        Without a quantity it closes the whole position, which is how the stop is placed. A
        take-profit carries its share of the position and can only reduce it.
        """
        whole = quantity is None
        result: dict[str, Any] = await self._signed(
            "POST",
            "/fapi/v1/algoOrder",
            {
                "algoType": "CONDITIONAL",
                "symbol": symbol,
                "side": side,
                "type": kind,
                "triggerPrice": trigger,
                "workingType": "MARK_PRICE",
                "priceProtect": True,
                "closePosition": True if whole else None,
                "quantity": quantity,
                "reduceOnly": None if whole else True,
                "clientAlgoId": client_id,
            },
        )
        return result

    async def open_algo_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        body = await self._signed("GET", "/fapi/v1/openAlgoOrders", {"symbol": symbol})
        orders: list[dict[str, Any]] = body if isinstance(body, list) else body.get("orders", [])
        return orders

    async def cancel_algo_orders(self, symbol: str) -> None:
        await self._signed("DELETE", "/fapi/v1/algoOpenOrders", {"symbol": symbol})
