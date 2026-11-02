"""Record a few real public Binance frames as test fixtures.

Fixtures are small and private (D006), and are labelled with their origin in meta.json.
No file from data.binance.vision is used. Run by hand; tests never call this.
"""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import websockets

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
CAPTURE_SECONDS = 70
MAX_FRAMES_PER_STREAM = 6


async def record_stream(url: str, target: Path) -> None:
    """Keep the first few frames per stream, plus every closing kline frame."""
    frames: list[dict[str, object]] = []
    counts: dict[str, int] = {}
    closing_seen = False
    loop = asyncio.get_running_loop()
    deadline = loop.time() + CAPTURE_SECONDS
    async with websockets.connect(url) as connection:
        while loop.time() < deadline and not closing_seen:
            raw = await asyncio.wait_for(connection.recv(), timeout=30)
            frame = json.loads(raw)
            stream = frame.get("stream", "unknown")
            is_closing = frame.get("data", {}).get("k", {}).get("x") is True
            closing_seen = closing_seen or is_closing
            if counts.get(stream, 0) < MAX_FRAMES_PER_STREAM or is_closing:
                frames.append(frame)
                counts[stream] = counts.get(stream, 0) + 1
    target.write_text(json.dumps(frames, indent=1) + "\n")


async def record_spot(client: httpx.AsyncClient) -> None:
    folder = FIXTURES / "binance_spot"
    folder.mkdir(parents=True, exist_ok=True)
    base = "https://api.binance.com/api/v3"
    time_response = await client.get(f"{base}/time")
    klines = await client.get(
        f"{base}/klines", params={"symbol": "BTCUSDT", "interval": "1m", "limit": 5}
    )
    rules = await client.get(f"{base}/exchangeInfo", params={"symbol": "BTCUSDT"})
    (folder / "time.json").write_text(time_response.text + "\n")
    (folder / "klines_btcusdt_1m.json").write_text(klines.text + "\n")
    (folder / "exchange_info_btcusdt.json").write_text(rules.text + "\n")
    await record_stream(
        "wss://stream.binance.com:9443/stream?streams=btcusdt@kline_1m/btcusdt@bookTicker",
        folder / "stream_frames.json",
    )


async def record_usdm(client: httpx.AsyncClient) -> None:
    folder = FIXTURES / "binance_usdm"
    folder.mkdir(parents=True, exist_ok=True)
    base = "https://fapi.binance.com"
    klines = await client.get(
        f"{base}/fapi/v1/klines", params={"symbol": "BTCUSDT", "interval": "1m", "limit": 5}
    )
    info = await client.get(f"{base}/fapi/v1/exchangeInfo")
    symbols = [s for s in info.json()["symbols"] if s["symbol"] == "BTCUSDT"]
    funding = await client.get(
        f"{base}/fapi/v1/fundingRate", params={"symbol": "BTCUSDT", "limit": 3}
    )
    premium = await client.get(f"{base}/fapi/v1/premiumIndex", params={"symbol": "BTCUSDT"})
    interest = await client.get(f"{base}/fapi/v1/openInterest", params={"symbol": "BTCUSDT"})
    history = await client.get(
        f"{base}/futures/data/openInterestHist",
        params={"symbol": "BTCUSDT", "period": "5m", "limit": 3},
    )
    (folder / "klines_btcusdt_1m.json").write_text(klines.text + "\n")
    (folder / "exchange_info_btcusdt.json").write_text(
        json.dumps({"symbols": symbols}, indent=1) + "\n"
    )
    (folder / "funding_rate.json").write_text(funding.text + "\n")
    (folder / "premium_index.json").write_text(premium.text + "\n")
    (folder / "open_interest.json").write_text(interest.text + "\n")
    (folder / "open_interest_hist.json").write_text(history.text + "\n")
    await asyncio.gather(
        record_stream(
            "wss://fstream.binance.com/market/stream?streams=btcusdt@kline_1m/btcusdt@markPrice@1s",
            folder / "market_stream_frames.json",
        ),
        record_stream(
            "wss://fstream.binance.com/public/stream?streams=btcusdt@bookTicker",
            folder / "public_stream_frames.json",
        ),
    )


async def main() -> None:
    async with httpx.AsyncClient(timeout=20) as client:
        await asyncio.gather(record_spot(client), record_usdm(client))
    meta = {
        "origin": "real public Binance responses",
        "recorded_at": datetime.now(UTC).isoformat(),
        "use": "private test fixtures only",
    }
    for name in ("binance_spot", "binance_usdm"):
        (FIXTURES / name / "meta.json").write_text(json.dumps(meta, indent=1) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
