"""Load history. The default profile is a 90-day test window (D027)."""

import argparse
import asyncio
import time

import structlog

from trading_intel.core.clock import SystemClock
from trading_intel.core.logging import configure_logging
from trading_intel.core.settings import load_settings
from trading_intel.data_providers.base import DerivativesCapable
from trading_intel.database.engine import create_engine
from trading_intel.database.repositories.candles import CandleRepository
from trading_intel.database.repositories.operations import (
    GapRepository,
    MarketRepository,
    RuleRepository,
    RunRepository,
)
from trading_intel.database.repositories.reference import ReferenceRepository
from trading_intel.entrypoints.wiring import (
    BINANCE_SPOT,
    BINANCE_USDM,
    EARLIEST,
    build_provider,
    git_sha,
)
from trading_intel.market_data.backfill import (
    FULL_PROFILE,
    HISTORY_PROFILE,
    HOLDOUT_PROFILE,
    RESEARCH_END,
    RESEARCH_START,
    TEST_PROFILE,
    BackfillProfile,
    BackfillService,
    plan_history_tasks,
    plan_holdout_tasks,
    plan_research_tasks,
    plan_tasks,
)
from trading_intel.market_data.instrument_rules import RuleSnapshotService

log = structlog.get_logger(__name__)


async def run(profile: BackfillProfile, codes: list[str], research: bool = False) -> None:
    settings = load_settings()
    configure_logging(settings.log_level, settings.secret_values())
    clock = SystemClock()
    engine = create_engine(settings.ingest_database_url)
    reference = ReferenceRepository(engine)
    candles = CandleRepository(engine)
    market = MarketRepository(engine)
    sha = git_sha()
    for code in codes:
        listed = await reference.provider_instruments(code)
        provider = build_provider(code, settings, clock, listed)
        provider_id = listed[0].provider_id
        service = BackfillService(
            provider,
            provider_id,
            candles,
            GapRepository(engine),
            RunRepository(engine),
            clock,
            git_sha=sha,
        )
        instruments = [
            (item.instrument, EARLIEST[(code, item.instrument.symbol)]) for item in listed
        ]
        now = await provider.get_server_time()
        history = profile is HISTORY_PROFILE
        holdout = profile is HOLDOUT_PROFILE
        if research:
            tasks = plan_research_tasks([item.instrument for item in listed])
        elif history:
            tasks = plan_history_tasks(instruments)
        elif holdout:
            tasks = plan_holdout_tasks([item.instrument for item in listed], now)
        else:
            tasks = plan_tasks(instruments, profile, now)
        started = time.monotonic()
        report = await service.run(tasks, profile.floor_bytes)
        await RuleSnapshotService(provider, provider_id, RuleRepository(engine), clock).refresh(
            [item.instrument for item in listed]
        )
        if provider.capabilities.funding and isinstance(provider, DerivativesCapable):
            for instrument, earliest in instruments:
                start = earliest if profile.window is None else max(earliest, now - profile.window)
                if research:
                    start = RESEARCH_START
                if holdout:
                    start = RESEARCH_END
                rows = [row async for row in provider.get_funding_history(instrument, start)]
                if history:
                    rows = [row for row in rows if row.funding_time < RESEARCH_END]
                await market.insert_funding(rows)
        log.info(
            "backfill_finished",
            provider=code,
            profile=profile.name,
            rows_added=report.rows_added,
            rows_expected=report.rows_expected,
            gaps=report.gaps,
            seconds=round(time.monotonic() - started, 1),
        )
        await provider.disconnect()
    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile", choices=["test", "full", "research", "history", "holdout"], default="test"
    )
    parser.add_argument("--providers", nargs="+", default=[BINANCE_SPOT, BINANCE_USDM])
    arguments = parser.parse_args()
    research = arguments.profile == "research"
    profile = {"full": FULL_PROFILE, "history": HISTORY_PROFILE, "holdout": HOLDOUT_PROFILE}.get(
        arguments.profile, TEST_PROFILE
    )
    asyncio.run(run(profile, arguments.providers, research))


if __name__ == "__main__":
    main()
