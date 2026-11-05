"""Kronos forecasts as labelled evidence (D040): make, study, resolve and report.

Usage, from backend/:
  uv run python -m trading_intel.entrypoints.forecast run BTCUSDT ETHUSDT
  uv run python -m trading_intel.entrypoints.forecast study BTCUSDT --first DAY --last DAY
  uv run python -m trading_intel.entrypoints.forecast resolve
  uv run python -m trading_intel.entrypoints.forecast report --write ../docs/reports/kronos-study.md

`run` forecasts from the latest stored 1H close and prints what Claude would read. `study`
forecasts each listed day from the close before it, on stored history only: the weights were
last changed on 2025-09-09, so those days are new to the model, and every outcome must resolve
before the holdout starts (D029). Nothing here places, sizes or changes a trade.
"""

import argparse
import asyncio
import json
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Final

from trading_intel.backtesting.windows import HOLDOUT_START
from trading_intel.core.clock import SystemClock
from trading_intel.core.settings import load_settings
from trading_intel.database.engine import create_engine
from trading_intel.database.repositories.candles import CandleRepository
from trading_intel.database.repositories.forecasts import ForecastRepository, Reason
from trading_intel.database.repositories.operations import RuleRepository
from trading_intel.database.repositories.reference import ProviderInstrument, ReferenceRepository
from trading_intel.domain.candles import Timeframe
from trading_intel.forecasting.kronos import ForecastUnavailableError, KronosRunner
from trading_intel.forecasting.service import LIVE, ForecastService
from trading_intel.forecasting.time_machine import VERSION as BASELINE_VERSION
from trading_intel.forecasting.time_machine import TimeMachineParameters
from trading_intel.forecasting.track_record import MINIMUM_FORECASTS, SourceRecord, TrackRecord
from trading_intel.market_structure.swings import find_swings
from trading_intel.technical_analysis.series import CandleSeries
from trading_intel.technical_analysis.volatility import atr
from trading_intel.trade_signals.catalogue import build_catalogue

PROVIDER: Final = "binance_usdm"  # Perpetuals only (D008).
TIMEFRAME: Final = Timeframe.H1  # The setup timeframe (D031).
WEIGHTS_CHANGED: Final = datetime(2025, 9, 9, 14, 10, 26, tzinfo=UTC)  # Hugging Face record.
NEAREST_LEVELS: Final = 3
REASONS: Final[dict[str, tuple[Reason, ...]]] = {
    "all": ("setup", "manual", "study"),
    "study": ("study",),
    "live": LIVE,
}


class Context:
    def __init__(self) -> None:
        self.engine = create_engine(load_settings().database_url)
        self.candles = CandleRepository(self.engine)
        self.runner = KronosRunner()
        self.service = ForecastService(
            self.candles,
            ForecastRepository(self.engine),
            self.runner,
            SystemClock(),
            holdout_start=HOLDOUT_START,
        )

    async def listed(self, symbols: Sequence[str]) -> list[ProviderInstrument]:
        found = {
            item.instrument.symbol: item
            for item in await ReferenceRepository(self.engine).provider_instruments(PROVIDER)
        }
        missing = [s for s in symbols if s not in found]
        if missing:
            raise SystemExit(f"not stored for {PROVIDER}: {', '.join(missing)}")
        return [found[s] for s in symbols]


async def run(context: Context, symbols: Sequence[str]) -> None:
    for item in await context.listed(symbols):
        provider, instrument = item.provider_id, item.instrument.id
        latest = await context.candles.latest_open_time(provider, instrument, TIMEFRAME)
        if latest is None:
            print(f"{item.instrument.symbol}: no 1H candles stored")
            continue
        try:
            stored = await context.service.forecast(
                provider, instrument, TIMEFRAME, TIMEFRAME.close_time(latest), "manual"
            )
        except ForecastUnavailableError as error:
            print(f"{item.instrument.symbol}: {error.message}")
            continue
        rows = await context.candles.for_analysis(
            provider, instrument, TIMEFRAME, stored.key.as_of, 400
        )
        rules = await RuleRepository(context.engine).current(provider, instrument)
        series = CandleSeries.of(rows)
        catalogue = (
            build_catalogue(series, find_swings(series), atr(series), rules.tick_size)
            if rules
            else None
        )
        levels = (
            []
            if catalogue is None
            else [
                (v.id, v.price)
                for v in [*catalogue.above()[:NEAREST_LEVELS], *catalogue.below()[:NEAREST_LEVELS]]
            ]
        )
        facts = await context.service.facts(stored, levels)
        print(json.dumps({"symbol": item.instrument.symbol, "forecast": facts}, indent=1))


async def study(context: Context, symbols: Sequence[str], first: date, last: date) -> None:
    """One forecast per outcome day, from the 1H close just before that day starts."""
    if datetime.combine(first, datetime.min.time(), UTC) <= WEIGHTS_CHANGED:
        raise SystemExit(f"the weights were last changed on {WEIGHTS_CHANGED:%Y-%m-%d}")
    context.runner.check()
    days = [first + timedelta(days=n) for n in range((last - first).days + 1)]
    for item in await context.listed(symbols):
        for day in days:
            as_of = datetime.combine(day, datetime.min.time(), UTC) - timedelta(milliseconds=1)
            try:
                stored = await context.service.forecast(
                    item.provider_id, item.instrument.id, TIMEFRAME, as_of, "study"
                )
            except ForecastUnavailableError as error:
                print(f"{item.instrument.symbol} {day}: {error.message}", flush=True)
                continue
            share = stored.summary["share_higher"]
            print(f"{item.instrument.symbol} {day}: {share:.0%} of paths end higher", flush=True)


async def report(context: Context, reasons: str, write: Path | None) -> None:
    config = context.runner.config
    record = await context.service.track_record(TIMEFRAME, REASONS[reasons])
    per_coin = {}
    for item in await ReferenceRepository(context.engine).provider_instruments(PROVIDER):
        coin = await context.service.track_record(
            TIMEFRAME, REASONS[reasons], instrument_id=item.instrument.id
        )
        if coin.count:
            per_coin[item.instrument.symbol] = coin
    text = render(record, per_coin, reasons, f"{config.model} at {config.model_revision[:7]}")
    if write is None:
        print(text)
    else:
        await asyncio.to_thread(write.write_text, text)
        print(f"wrote {write}")


def _pct(value: float) -> str:
    return f"{value:.0%}"


def _bands(model: SourceRecord, baseline: SourceRecord) -> list[str]:
    names = {"high": "Highest price", "low": "Lowest price", "close": "Close after 24 hours"}
    return [
        f"| {label} | {_pct(model.inside_band[m])} | {_pct(baseline.inside_band[m])} | 80% |"
        for m, label in names.items()
    ]


def render(record: TrackRecord, per_coin: dict[str, TrackRecord], reasons: str, model: str) -> str:
    lines = [
        "# Kronos Forecast Track Record",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by `trading_intel.entrypoints.forecast"
        f" report --reasons {reasons}`. Model: {model}, 30 paths, 24 1H candles ahead. Baseline:"
        f" time machine version {BASELINE_VERSION}, {TimeMachineParameters().paths:,} paths"
        " resampled from the coin's last 60 days. Personal research data (D006).",
        "",
        f"**Resolved forecasts: {record.count}. Status: {record.status}.** The status needs at"
        f' least {MINIMUM_FORECASTS} forecasts, and turns "better than baseline" only when both'
        " scores below favour Kronos with 95% confidence.",
    ]
    model_record, baseline_record = record.model, record.baseline
    if model_record is None or baseline_record is None:
        return "\n".join([*lines, "", "No forecast has resolved yet.", ""])
    brier, crps = record.brier_difference, record.crps_difference
    assert brier is not None and crps is not None
    lines += [
        "",
        "## Direction",
        "",
        "Each forecast says what share of its paths end higher after 24 hours. The Brier score"
        " measures how far that share was from what happened: 0 is perfect, and always saying"
        " 50% scores 0.25.",
        "",
        "| | Kronos | Baseline | Always 50% |",
        "|---|---|---|---|",
        f"| Brier score | {model_record.brier:.3f} | {baseline_record.brier:.3f} | 0.250 |",
        "",
        f"Kronos minus baseline: {brier.mean:+.3f}, 95% interval {brier.low:+.3f} to"
        f" {brier.high:+.3f}. Below zero favours Kronos.",
        "",
        "| Kronos said, share ending higher | Forecasts | Average said | Actually ended higher |",
        "|---|---|---|---|",
        *[
            f"| {b.low:.0%} to {b.high:.0%} | {b.count} | "
            + ("-" if b.mean_forecast is None else _pct(b.mean_forecast))
            + " | "
            + ("-" if b.observed is None else _pct(b.observed))
            + " |"
            for b in model_record.reliability
        ],
        "",
        "## Range",
        "",
        "How often the real value fell inside each forecast's 10th to 90th percentile band. An"
        " honest band holds it 80% of the time. Less means the forecast was overconfident.",
        "",
        "| Measure | Kronos | Baseline | Honest band |",
        "|---|---|---|---|",
        *_bands(model_record, baseline_record),
        "",
        "## Whole Distribution",
        "",
        "The continuous ranked probability score of the 24-hour close, in percent of price."
        " Lower is better.",
        "",
        "| | Kronos | Baseline |",
        "|---|---|---|",
        f"| CRPS | {model_record.close_crps_pct:.3f}% | {baseline_record.close_crps_pct:.3f}% |",
        "",
        f"Kronos minus baseline: {crps.mean:+.3f}, 95% interval {crps.low:+.3f} to"
        f" {crps.high:+.3f} percentage points.",
        "",
        "Where each real close fell among the forecast's closes, in tenths. A calibrated"
        " forecast spreads evenly. Piles at both ends mean bands that are too narrow.",
        "",
        "| Tenth | " + " | ".join(str(n) for n in range(1, 11)) + " |",
        "|---|" + "---|" * 10,
        "| Kronos | " + " | ".join(str(c) for c in model_record.close_level_counts) + " |",
        "| Baseline | " + " | ".join(str(c) for c in baseline_record.close_level_counts) + " |",
        "",
        "## By Coin",
        "",
        "| Coin | Forecasts | Brier, Kronos | Brier, baseline | CRPS, Kronos | CRPS, baseline |",
        "|---|---|---|---|---|---|",
    ]
    for symbol, coin in per_coin.items():
        if coin.model is None or coin.baseline is None:
            lines.append(f"| {symbol} | 0 | - | - | - | - |")
            continue
        lines.append(
            f"| {symbol} | {coin.count} | {coin.model.brier:.3f} | {coin.baseline.brier:.3f} |"
            f" {coin.model.close_crps_pct:.3f}% | {coin.baseline.close_crps_pct:.3f}% |"
        )
    lines += [
        "",
        "## Limits",
        "",
        "- Kronos samples 30 paths, so its shares move in steps of about 3% and its tails are"
        " rough. The baseline samples 10,000.",
        "- The intervals assume forecasts are independent. Forecasts whose 24 hours overlap are"
        " not, which makes the intervals too narrow.",
        "- Study days are new to the model, whose weights were last changed on 2025-09-09. Days"
        " before that may be in its training data and are never used.",
        "- A score that favours Kronos still says nothing about profit after costs.",
        "",
    ]
    return "\n".join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("run").add_argument("symbols", nargs="+")
    studied = commands.add_parser("study")
    studied.add_argument("symbols", nargs="+")
    studied.add_argument("--first", type=date.fromisoformat, required=True)
    studied.add_argument("--last", type=date.fromisoformat, required=True)
    commands.add_parser("resolve")
    reported = commands.add_parser("report")
    reported.add_argument("--reasons", choices=sorted(REASONS), default="all")
    reported.add_argument("--write", type=Path)
    arguments = parser.parse_args()

    context = Context()
    try:
        if arguments.command == "run":
            await run(context, arguments.symbols)
        elif arguments.command == "study":
            await study(context, arguments.symbols, arguments.first, arguments.last)
        elif arguments.command == "resolve":
            resolved, waiting = await context.service.resolve_due()
            print(f"resolved {resolved} forecasts, {waiting} still waiting for candles")
        else:
            await report(context, arguments.reasons, arguments.write)
    finally:
        await context.engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
