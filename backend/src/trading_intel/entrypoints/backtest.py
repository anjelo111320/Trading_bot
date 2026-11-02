"""Run the rule baseline over stored candles. Windows touching the holdout are refused."""

import argparse
import asyncio
from datetime import UTC, datetime, timedelta

from trading_intel.backtesting.engine import BacktestEngine, BacktestResult, CostModel, FundingEvent
from trading_intel.backtesting.report import render
from trading_intel.backtesting.windows import refuse_holdout
from trading_intel.core.settings import REPOSITORY_ROOT, load_settings
from trading_intel.database.engine import create_engine
from trading_intel.database.repositories.candles import CandleRepository
from trading_intel.database.repositories.operations import MarketRepository, RuleRepository
from trading_intel.database.repositories.reference import ReferenceRepository
from trading_intel.domain.candles import ClosedCandle, Timeframe

WARM_UP = timedelta(days=30)
STRESS_LEVELS = ("1", "1.5", "2")


async def run(symbol: str, start: datetime, end: datetime) -> str:
    refuse_holdout(start, end)
    engine = create_engine(load_settings().database_url)
    listed = await ReferenceRepository(engine).provider_instruments("binance_usdm")
    item = next(entry for entry in listed if entry.instrument.symbol == symbol)
    provider, instrument = item.provider_id, item.instrument
    candles = CandleRepository(engine)
    rules = await RuleRepository(engine).current(provider, instrument.id)
    assert rules is not None, "instrument rules are required"

    async def load(timeframe: Timeframe) -> list[ClosedCandle]:
        return await candles.range(provider, instrument.id, timeframe, start - WARM_UP, end)

    minutes = await load(Timeframe.M1)
    setup = await load(Timeframe.M15)
    middle = await load(Timeframe.H1)
    higher = await load(Timeframe.H4)
    rows = await MarketRepository(engine).funding_between(provider, instrument.id, start, end)
    funding = [FundingEvent(at, rate, mark) for at, rate, mark in rows if mark is not None]
    await engine.dispose()

    results: dict[str, BacktestResult] = {}
    for level in STRESS_LEVELS:
        costs = CostModel().stressed(level)
        results[level] = BacktestEngine(
            instrument, rules, minutes, setup, middle, higher, funding, costs=costs
        ).run(start, end)

    notes = [
        "Real perpetual candles from before the frozen holdout (D029).",
        "This window only proves the engine runs. It is far too short to be evidence of edge.",
        "Instrument rules are today's snapshot, used as a proxy for that period.",
        "Spread and slippage are conservative assumptions, not recorded values.",
        "BTC and ETH were chosen with hindsight, which is survivorship bias.",
    ]
    text = render(f"Baseline Backtest: {symbol} perpetual", results["1"], notes)
    for level in STRESS_LEVELS[1:]:
        stressed = results[level].metrics
        assert stressed is not None
        text += (
            f"- At {level}x costs: net P/L {stressed.net_pnl:.2f}, trades {stressed.trades}, "
            f"profit factor {stressed.profit_factor}\n"
        )
    print(text)
    if output is not None:
        output.write_text(text)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--start", default="2025-08-01")
    parser.add_argument("--end", default="2025-11-01")
    parser.add_argument("--output")
    arguments = parser.parse_args()
    start = datetime.fromisoformat(arguments.start).replace(tzinfo=UTC)
    end = datetime.fromisoformat(arguments.end).replace(tzinfo=UTC)
    text = asyncio.run(run(arguments.symbol, start, end))
    print(text)  # noqa: T201
    if arguments.output:
        (REPOSITORY_ROOT / arguments.output).write_text(text)


if __name__ == "__main__":
    main()
