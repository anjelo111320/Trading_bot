"""What the system sees right now: strategies, patterns, levels and regime at the latest close.

Usage:
  uv run python scripts/live_snapshot.py [SYMBOL ...]                   stored candles
  uv run python scripts/live_snapshot.py --source binance SOLUSDT     public Binance data

Read-only. It decides at the latest closed candles, exactly as a live run would, and places
no order. The Binance source previews a coin the system does not store yet: candles are read
into memory from public endpoints, forming candles are dropped, and nothing is saved.
"""

import argparse
import asyncio
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from trading_intel.core.settings import load_settings
from trading_intel.database.engine import create_engine
from trading_intel.database.repositories.candles import CandleRepository
from trading_intel.database.repositories.operations import MarketRepository, RuleRepository
from trading_intel.database.repositories.reference import ReferenceRepository
from trading_intel.domain.base import DataOrigin
from trading_intel.domain.candles import ClosedCandle, Timeframe
from trading_intel.market_structure.swings import find_swings
from trading_intel.pattern_detection.describe import describe
from trading_intel.technical_analysis.momentum import rsi
from trading_intel.technical_analysis.series import CandleSeries
from trading_intel.trade_signals.catalogue import build_catalogue
from trading_intel.trade_signals.pattern_strategy import PatternStrategy
from trading_intel.trade_signals.trend_strategy import DailyTrendStrategy

RECENT_HOURS = 72
FAPI = "https://fapi.binance.com"


@dataclass(frozen=True)
class Market:
    hours: list[ClosedCandle]
    fours: list[ClosedCandle]
    days: list[ClosedCandle]
    funding: list[tuple[datetime, Decimal, Decimal | None]]
    tick: Decimal


async def from_database(symbol: str) -> Market:
    engine = create_engine(load_settings().database_url)
    listed = await ReferenceRepository(engine).provider_instruments("binance_usdm")
    item = next(entry for entry in listed if entry.instrument.symbol == symbol)
    provider, instrument = item.provider_id, item.instrument
    rules = await RuleRepository(engine).current(provider, instrument.id)
    assert rules is not None
    now = datetime.now(UTC)
    candles = CandleRepository(engine)

    async def load(timeframe: Timeframe, since: datetime) -> list[ClosedCandle]:
        return await candles.range(provider, instrument.id, timeframe, since, now)

    market = Market(
        hours=await load(Timeframe.H1, now - timedelta(days=60)),
        fours=await load(Timeframe.H4, now - timedelta(days=200)),
        days=await load(Timeframe.D1, datetime(2019, 1, 1, tzinfo=UTC)),
        funding=await MarketRepository(engine).funding_between(
            provider, instrument.id, now - timedelta(days=2), now
        ),
        tick=rules.tick_size,
    )
    await engine.dispose()
    return market


def _get(path: str, **params: object) -> Any:
    url = f"{FAPI}{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 - fixed https host
        return json.load(response)


def _klines(symbol: str, timeframe: Timeframe, limit: int, now: datetime) -> list[ClosedCandle]:
    found: list[ClosedCandle] = []
    for row in _get("/fapi/v1/klines", symbol=symbol, interval=timeframe.value, limit=limit):
        opened = datetime.fromtimestamp(row[0] / 1000, UTC)
        closes = timeframe.close_time(opened)
        if closes >= now:
            continue  # The forming candle never enters analysis (D013).
        found.append(
            ClosedCandle(
                provider_id=1,
                instrument_id=1,
                timeframe=timeframe,
                open_time=opened,
                close_time=closes,
                open=Decimal(row[1]),
                high=Decimal(row[2]),
                low=Decimal(row[3]),
                close=Decimal(row[4]),
                volume=Decimal(row[5]),
                quote_volume=Decimal(row[7]),
                taker_buy_base_volume=Decimal(row[9]),
                trade_count=int(row[8]),
                provider_open_time_raw=int(row[0]),
                data_origin=DataOrigin.BACKFILL,
                received_at=now,
            )
        )
    return found


def from_binance(symbol: str) -> Market:
    now = datetime.now(UTC)
    info = _get("/fapi/v1/exchangeInfo")
    spec = next(s for s in info["symbols"] if s["symbol"] == symbol)
    tick = next(
        Decimal(f["tickSize"]) for f in spec["filters"] if f["filterType"] == "PRICE_FILTER"
    )
    rates = _get("/fapi/v1/fundingRate", symbol=symbol, limit=3)
    return Market(
        hours=_klines(symbol, Timeframe.H1, 1440, now),
        fours=_klines(symbol, Timeframe.H4, 1200, now),
        days=_klines(symbol, Timeframe.D1, 1500, now),
        funding=[
            (
                datetime.fromtimestamp(r["fundingTime"] / 1000, UTC),
                Decimal(r["fundingRate"]),
                Decimal(r["markPrice"]) if r.get("markPrice") else None,
            )
            for r in rates
        ],
        tick=tick.normalize(),
    )


def _decision(decision: Any) -> dict[str, Any]:
    proposal = decision.proposal
    return {
        "action": decision.action.value,
        "reasons": list(decision.reasons),
        "proposal": None
        if proposal is None
        else {
            "side": proposal.side.value,
            "entry_type": proposal.entry_type.value,
            "entry": str(proposal.entry),
            "stop": str(proposal.stop),
            "targets": [str(t) for t in proposal.targets],
        },
    }


def analyse(symbol: str, market: Market) -> dict[str, Any]:
    tick = market.tick
    pattern = PatternStrategy(market.hours, market.fours, market.days, tick)
    trend = DailyTrendStrategy(market.days, tick)
    series = pattern.series
    last_hour, last_day = series.close_time[-1], trend.series.close_time[-1]
    middle, higher = pattern.trends_at(last_hour)
    regime = pattern.regimes.at(last_hour)

    recent = [
        p
        for moment, found in pattern.breakouts.items()
        if moment >= last_hour - timedelta(hours=RECENT_HOURS)
        for p in found
    ]
    window = series.window(len(series) - 400, len(series))
    catalogue = build_catalogue(window, find_swings(window), pattern.atr[-400:], tick)
    assert catalogue is not None
    above, below = catalogue.above()[:6], catalogue.below()[:6]

    daily = trend.series
    channel = slice(len(daily) - 21, len(daily) - 1)
    exits = slice(len(daily) - 10, len(daily))
    hourly_rsi, four_rsi = rsi(series.close), rsi(CandleSeries.of(market.fours).close)
    return {
        "symbol": symbol,
        "as_of_1h_close": last_hour.isoformat(),
        "as_of_1d_close": last_day.isoformat(),
        "last_close": float(series.close[-1]),
        "atr_1h": round(float(pattern.atr[-1]), 4),
        "atr_1d": round(float(trend.atr[-1]), 4),
        "rsi_1h": round(float(hourly_rsi[-1]), 1),
        "rsi_4h": round(float(four_rsi[-1]), 1),
        "trend_4h": middle,
        "trend_1d": higher,
        "regime": {
            "trend": regime.trend,
            "volatility": regime.volatility,
            "adx_1d": regime.adx,
            "volatility_percentile": regime.volatility_percentile,
        },
        "funding_latest": [
            {"at": at.isoformat(), "rate": str(rate)} for at, rate, _ in market.funding[-3:]
        ],
        "pattern_strategy_now": _decision(pattern.decide(last_hour)),
        "chart_patterns_last_72h": [
            {
                "facts": describe(p, series, pattern.atr),
                "invalidated_at": p.invalidated_at.isoformat() if p.invalidated_at else None,
                "decision_then": _decision(pattern.decide(p.detected_at)),
            }
            for p in sorted(recent, key=lambda p: p.detected_at)
        ],
        "candle_patterns_last_6h": [
            {
                "type": p.pattern_type,
                "direction": p.direction.value,
                "at": p.detected_at.isoformat(),
            }
            for moment, found in sorted(pattern.candles.items())
            if moment >= last_hour - timedelta(hours=6)
            for p in found
        ],
        "trend_strategy_now": _decision(trend.decide(last_day)),
        "trend_channel": {
            "prior_20d_high": float(daily.high[channel].max()),
            "prior_20d_low": float(daily.low[channel].min()),
            "last_daily_close": float(daily.close[-1]),
            "exit_10d_low": float(daily.low[exits].min()),
            "exit_10d_high": float(daily.high[exits].max()),
        },
        "levels_above": [
            {"id": v.id, "kind": v.kind, "price": str(v.price), "evidence": v.evidence}
            for v in above
        ],
        "levels_below": [
            {"id": v.id, "kind": v.kind, "price": str(v.price), "evidence": v.evidence}
            for v in below
        ],
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbols", nargs="*", default=["BTCUSDT", "ETHUSDT"])
    parser.add_argument("--source", choices=["db", "binance"], default="db")
    arguments = parser.parse_args()
    for symbol in arguments.symbols:
        market = (
            from_binance(symbol) if arguments.source == "binance" else await from_database(symbol)
        )
        print(json.dumps(analyse(symbol, market), indent=1, default=str))


if __name__ == "__main__":
    asyncio.run(main())
