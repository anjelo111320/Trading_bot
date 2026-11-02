import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import respx

from trading_intel.core.clock import FixedClock, to_epoch_ms
from trading_intel.core.errors import ProviderError, ProviderHaltError
from trading_intel.data_providers.binance.provider import SPOT, USDM, BinanceProvider, Venue
from trading_intel.data_providers.binance.rest import BinanceRestClient, WeightLimiter
from trading_intel.domain.candles import Timeframe
from trading_intel.domain.instruments import Instrument, InstrumentType

BASE = "https://binance.test"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
START = datetime(2026, 1, 1, tzinfo=UTC)
BTC = Instrument(
    id=1,
    symbol="BTCUSDT",
    instrument_type=InstrumentType.SPOT,
    base_asset="BTC",
    quote_asset="USDT",
    settle_asset="USDT",
)


class Sleeps:
    def __init__(self, clock: FixedClock) -> None:
        self.clock = clock
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        self.clock.advance(seconds)


def build(venue: Venue = SPOT, cap: int = 1500) -> tuple[BinanceRestClient, Sleeps]:
    clock = FixedClock(START)
    sleeps = Sleeps(clock)
    client = BinanceRestClient(BASE, venue.allowed_paths, cap, clock, sleep=sleeps)
    return client, sleeps


def provider(rest: BinanceRestClient, clock: FixedClock) -> BinanceProvider:
    return BinanceProvider(SPOT, 1, {1: "BTCUSDT"}, rest, "wss://binance.test", clock)


def kline(open_time: datetime, timeframe: Timeframe = Timeframe.M1) -> list[object]:
    close_time = timeframe.close_time(open_time)
    return [
        to_epoch_ms(open_time),
        "100",
        "110",
        "90",
        "105",
        "5",
        to_epoch_ms(close_time),
        "500",
        3,
        "2",
        "200",
        "0",
    ]


async def test_path_outside_the_allow_list_is_refused_without_a_request() -> None:
    client, _ = build()
    with respx.mock(assert_all_called=False) as router:
        with pytest.raises(ProviderError, match="allow-list"):
            await client.get("/api/v3/order", {}, 1)
        assert router.calls.call_count == 0


def test_client_has_no_method_that_could_place_an_order() -> None:
    client, _ = build()
    for verb in ("post", "put", "patch", "delete"):
        assert not hasattr(client, verb)


@pytest.mark.parametrize("venue", [SPOT, USDM])
def test_no_order_or_account_path_is_allowed(venue: Venue) -> None:
    for path in venue.allowed_paths:
        assert "order" not in path.lower().replace("forceorder", "")
        assert "account" not in path.lower()


@respx.mock
async def test_requests_carry_no_key_or_signature() -> None:
    route = respx.get(f"{BASE}/api/v3/time").mock(
        return_value=httpx.Response(200, json={"serverTime": to_epoch_ms(START)})
    )
    client, _ = build()
    await client.get("/api/v3/time", {}, 1)
    request = route.calls[0].request
    assert "x-mbx-apikey" not in {name.lower() for name in request.headers}
    assert "signature" not in str(request.url)


@pytest.mark.parametrize("status", [403, 418, 451])
@respx.mock
async def test_refusal_is_a_hard_stop_and_stays_stopped(status: int) -> None:
    route = respx.get(f"{BASE}/api/v3/time").mock(return_value=httpx.Response(status))
    client, sleeps = build()
    with pytest.raises(ProviderHaltError):
        await client.get("/api/v3/time", {}, 1)
    with pytest.raises(ProviderHaltError):
        await client.get("/api/v3/time", {}, 1)
    assert route.call_count == 1
    assert sleeps.calls == []


@respx.mock
async def test_429_honours_retry_after_and_lowers_the_cap() -> None:
    respx.get(f"{BASE}/api/v3/time").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    client, sleeps = build(cap=1000)
    assert await client.get("/api/v3/time", {}, 1) == {"ok": True}
    assert sleeps.calls == [7.0]
    assert client.limiter.cap == 500


@respx.mock
async def test_server_errors_back_off_and_recover() -> None:
    respx.get(f"{BASE}/api/v3/time").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json={"ok": True})]
    )
    client, sleeps = build()
    assert await client.get("/api/v3/time", {}, 1) == {"ok": True}
    assert len(sleeps.calls) == 1


@respx.mock
async def test_timeouts_retry_with_a_limit() -> None:
    route = respx.get(f"{BASE}/api/v3/time").mock(side_effect=httpx.ConnectTimeout("slow"))
    client, sleeps = build()
    with pytest.raises(ProviderError, match="failed after 5 attempts"):
        await client.get("/api/v3/time", {}, 1)
    assert route.call_count == 5
    assert sleeps.calls[1] > sleeps.calls[0]


@respx.mock
async def test_client_errors_are_not_retried() -> None:
    route = respx.get(f"{BASE}/api/v3/time").mock(return_value=httpx.Response(400, text="bad"))
    client, _ = build()
    with pytest.raises(ProviderError, match="400"):
        await client.get("/api/v3/time", {}, 1)
    assert route.call_count == 1


async def test_limiter_waits_for_the_next_minute_at_the_cap() -> None:
    clock = FixedClock(START + timedelta(seconds=45))
    sleeps = Sleeps(clock)
    limiter = WeightLimiter(10, clock, sleeps)
    await limiter.acquire(10)
    await limiter.acquire(1)
    assert sleeps.calls == [15.0]
    assert limiter.used == 1


async def test_limiter_trusts_the_providers_higher_count() -> None:
    clock = FixedClock(START)
    sleeps = Sleeps(clock)
    limiter = WeightLimiter(100, clock, sleeps)
    await limiter.acquire(1)
    limiter.observe(100)
    await limiter.acquire(1)
    assert sleeps.calls == [60.0]


@respx.mock
async def test_used_weight_header_updates_the_limiter() -> None:
    respx.get(f"{BASE}/api/v3/time").mock(
        return_value=httpx.Response(200, json={"ok": True}, headers={"X-MBX-USED-WEIGHT-1M": "321"})
    )
    client, _ = build()
    await client.get("/api/v3/time", {}, 1)
    assert client.limiter.used == 321


@respx.mock
async def test_history_pages_through_and_stops_before_the_forming_candle() -> None:
    now = START + timedelta(minutes=2500, seconds=30)
    first = [kline(START + timedelta(minutes=m)) for m in range(1000)]
    second = [kline(START + timedelta(minutes=m)) for m in range(1000, 2000)]
    third = [kline(START + timedelta(minutes=m)) for m in range(2000, 2501)]
    route = respx.get(f"{BASE}/api/v3/klines").mock(
        side_effect=[
            httpx.Response(200, json=first),
            httpx.Response(200, json=second),
            httpx.Response(200, json=third),
        ]
    )
    respx.get(f"{BASE}/api/v3/time").mock(
        return_value=httpx.Response(200, json={"serverTime": to_epoch_ms(now)})
    )
    clock = FixedClock(now)
    rest = BinanceRestClient(BASE, SPOT.allowed_paths, 1500, clock, sleep=Sleeps(clock))
    candles = [
        c async for c in provider(rest, clock).get_historical_candles(BTC, Timeframe.M1, START, now)
    ]
    assert len(candles) == 2500
    assert candles[-1].close_time < now
    assert route.call_count == 3
    assert route.calls[1].request.url.params["startTime"] == str(
        to_epoch_ms(START + timedelta(minutes=1000))
    )


@respx.mock
async def test_rules_come_from_the_recorded_format() -> None:
    body = json.loads((FIXTURES / "binance_spot/exchange_info_btcusdt.json").read_text())
    respx.get(f"{BASE}/api/v3/exchangeInfo").mock(return_value=httpx.Response(200, json=body))
    clock = FixedClock(START)
    rest = BinanceRestClient(BASE, SPOT.allowed_paths, 1500, clock, sleep=Sleeps(clock))
    rules = await provider(rest, clock).get_instrument_rules(BTC)
    assert rules.tick_size == Decimal("0.01")


@respx.mock
async def test_open_interest_history_pages_through_the_whole_window() -> None:
    """Regression: without endTime Binance returns only the newest 500 rows."""
    now = START + timedelta(days=4)

    def answer(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        assert "endTime" in params
        first, last = int(params["startTime"]), int(params["endTime"])
        step = 300_000
        rows = [
            {"sumOpenInterest": "100.5", "timestamp": moment} for moment in range(first, last, step)
        ]
        return httpx.Response(200, json=rows)

    route = respx.get(f"{BASE}/futures/data/openInterestHist").mock(side_effect=answer)
    clock = FixedClock(now)
    rest = BinanceRestClient(BASE, USDM.allowed_paths, 600, clock, sleep=Sleeps(clock))
    live = BinanceProvider(USDM, 1, {1: "BTCUSDT"}, rest, "wss://binance.test", clock)
    rows = [row async for row in live.get_open_interest_history(BTC, START)]
    assert len(rows) == 4 * 24 * 12
    assert route.call_count == 3
    assert rows[0].event_time == START
    assert rows[-1].event_time == now - timedelta(minutes=5)


@pytest.mark.live
async def test_live_binance_still_behaves_as_documented() -> None:
    """Opt-in smoke test: uv run pytest --live -m live"""
    clock = FixedClock(datetime.now(UTC))
    rest = BinanceRestClient("https://api.binance.com", SPOT.allowed_paths, 100, clock)
    live = provider(rest, clock)
    server_time = await live.get_server_time()
    assert abs(server_time - datetime.now(UTC)) < timedelta(seconds=30)
    start = Timeframe.M1.floor(server_time) - timedelta(minutes=5)
    candles = [c async for c in live.get_historical_candles(BTC, Timeframe.M1, start, server_time)]
    assert 4 <= len(candles) <= 5
    assert candles[-1].close_time < server_time
    await live.disconnect()
