"""Exchange rules cannot be fetched for past dates, so they are recorded going forward."""

from collections.abc import Sequence

from trading_intel.core.clock import Clock
from trading_intel.data_providers.base import MarketDataProvider
from trading_intel.database.repositories.operations import RuleRepository
from trading_intel.domain.instruments import Instrument

REFRESH_SECONDS = 6 * 3600


class RuleSnapshotService:
    def __init__(
        self,
        provider: MarketDataProvider,
        provider_id: int,
        rules: RuleRepository,
        clock: Clock,
    ) -> None:
        self._provider = provider
        self._provider_id = provider_id
        self._rules = rules
        self._clock = clock

    async def refresh(self, instruments: Sequence[Instrument]) -> int:
        """Store a new row only when the rules changed. Returns how many changed."""
        changed = 0
        for instrument in instruments:
            latest = await self._provider.get_instrument_rules(instrument)
            current = await self._rules.current(self._provider_id, instrument.id)
            if current is None or not current.same_terms_as(latest):
                await self._rules.replace_current(
                    self._provider_id, instrument.id, latest, self._clock.now()
                )
                changed += 1
        return changed
