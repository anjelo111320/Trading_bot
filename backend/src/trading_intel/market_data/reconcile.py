"""Compare stored candles with the provider. A difference leaves an audit record."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

import structlog

from trading_intel.core.clock import Clock
from trading_intel.data_providers.base import MarketDataProvider
from trading_intel.database.repositories.candles import CandleRepository, differences
from trading_intel.domain.base import DataOrigin
from trading_intel.domain.candles import ClosedCandle, Timeframe
from trading_intel.domain.instruments import Instrument

log = structlog.get_logger(__name__)

SWEEP_SECONDS = 300
SWEEP_CANDLES = 5
SETTLE_MARGIN = timedelta(seconds=30)


@dataclass(frozen=True)
class SweepResult:
    checked: int
    recovered: int
    mismatched: int


@dataclass(frozen=True)
class Aggregate:
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


def aggregate(candles: Sequence[ClosedCandle]) -> Aggregate:
    """Combine smaller candles, ordered oldest first, into one bar."""
    return Aggregate(
        open=candles[0].open,
        high=max(c.high for c in candles),
        low=min(c.low for c in candles),
        close=candles[-1].close,
        volume=sum((c.volume for c in candles), Decimal(0)),
    )


def aggregate_differences(native: ClosedCandle, built: Aggregate) -> list[str]:
    return [
        name
        for name in ("open", "high", "low", "close", "volume")
        if getattr(native, name) != getattr(built, name)
    ]


class ReconcileService:
    def __init__(
        self,
        provider: MarketDataProvider,
        provider_id: int,
        candles: CandleRepository,
        clock: Clock,
    ) -> None:
        self._provider = provider
        self._provider_id = provider_id
        self._candles = candles
        self._clock = clock

    async def sweep(self, instrument: Instrument, timeframe: Timeframe) -> SweepResult:
        """Check the latest closed candles, recovering any whose closing frame was lost."""
        # Futures REST values are not final for a few seconds after a candle closes, so a sweep
        # any sooner replaced correct live candles with partial ones, as seen on 2026-11-02.
        end = timeframe.floor(self._clock.now() - SETTLE_MARGIN)
        start = end - timeframe.delta * SWEEP_CANDLES
        stored = {
            c.open_time: c
            for c in await self._candles.range(
                self._provider_id, instrument.id, timeframe, start, end
            )
        }
        checked = recovered = mismatched = 0
        async for remote in self._provider.get_historical_candles(
            instrument, timeframe, start, end, DataOrigin.BACKFILL
        ):
            checked += 1
            local = stored.get(remote.open_time)
            if local is None:
                recovered += await self._candles.insert([remote])
            elif fields := differences(local, remote):
                mismatched += 1
                log.warning(
                    "candle_mismatch",
                    instrument=instrument.symbol,
                    timeframe=timeframe.value,
                    open_time=remote.open_time.isoformat(),
                    fields=fields,
                )
                await self._candles.replace_with_revision(
                    local, remote, f"reconcile mismatch: {', '.join(fields)}"
                )
        return SweepResult(checked, recovered, mismatched)

    async def cross_check(
        self, instrument: Instrument, higher: Timeframe, open_time: datetime
    ) -> list[str]:
        """Compare a native candle with its 1M parts. Returns the fields that disagree."""
        close = higher.next_open(open_time)
        natives = await self._candles.range(
            self._provider_id, instrument.id, higher, open_time, close
        )
        minutes = await self._candles.range(
            self._provider_id, instrument.id, Timeframe.M1, open_time, close
        )
        expected_minutes = higher.seconds // Timeframe.M1.seconds
        if len(natives) != 1 or len(minutes) != expected_minutes:
            return ["incomplete"]
        return aggregate_differences(natives[0], aggregate(minutes))
