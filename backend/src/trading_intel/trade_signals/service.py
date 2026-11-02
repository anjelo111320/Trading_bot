"""Turn a closed setup candle into a risk-checked signal.

Every proposal passes through the risk engine, and a rejection is stored with its reasons.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final
from uuid import UUID

import structlog

from trading_intel.core.clock import Clock
from trading_intel.database.repositories.candles import CandleRepository
from trading_intel.database.repositories.operations import (
    GapRepository,
    MarketRepository,
    RuleRepository,
    SnapshotRepository,
)
from trading_intel.database.repositories.paper import PaperRepository
from trading_intel.database.repositories.signals import (
    Account,
    NewRecommendation,
    SignalRepository,
)
from trading_intel.domain.candles import Timeframe
from trading_intel.domain.instruments import Instrument, InstrumentRules
from trading_intel.domain.signals import Action
from trading_intel.risk_management.engine import assess
from trading_intel.risk_management.models import (
    MarketState,
    RiskRequest,
    Sizing,
    TradeProposal,
)
from trading_intel.technical_analysis.series import CandleSeries
from trading_intel.technical_analysis.volatility import atr
from trading_intel.trade_signals.baseline import (
    STRATEGY_NAME,
    STRATEGY_VERSION,
    BaselineParameters,
    evaluate,
)
from trading_intel.trade_signals.lifecycle import dedupe_key
from trading_intel.trade_signals.quality import SetupEvidence, score_setup

log = structlog.get_logger(__name__)

SETUP_LOOKBACK: Final = 400
MIDDLE_LOOKBACK: Final = 200
HIGHER_LOOKBACK: Final = 150
MINUTE_LOOKBACK: Final = 30
SLIPPAGE_TICKS: Final = 2
SLIPPAGE_ATR_SHARE: Final = Decimal("0.05")
HOLD_FUNDING_INTERVALS: Final = 1
MAKER_FEE_FALLBACK: Final = Decimal("0.0002")


@dataclass(frozen=True)
class SignalOutcome:
    action: Action
    recommendation_id: UUID | None
    approved: bool
    reasons: tuple[str, ...]


class SignalService:
    def __init__(
        self,
        candles: CandleRepository,
        snapshots: SnapshotRepository,
        market: MarketRepository,
        gaps: GapRepository,
        rules: RuleRepository,
        signals: SignalRepository,
        paper: PaperRepository,
        clock: Clock,
        parameters: BaselineParameters | None = None,
    ) -> None:
        self._candles = candles
        self._snapshots = snapshots
        self._market = market
        self._gaps = gaps
        self._rules = rules
        self._signals = signals
        self._paper = paper
        self._clock = clock
        self._parameters = parameters or BaselineParameters()

    async def _closed(
        self, provider_id: int, instrument: Instrument, timeframe: Timeframe, at: datetime, n: int
    ) -> CandleSeries | None:
        rows = await self._candles.for_analysis(provider_id, instrument.id, timeframe, at, n)
        return CandleSeries.of(rows) if rows else None

    async def evaluate(
        self, provider_id: int, instrument: Instrument, as_of: datetime, account: Account
    ) -> SignalOutcome:
        setup = await self._closed(provider_id, instrument, Timeframe.M15, as_of, SETUP_LOOKBACK)
        middle = await self._closed(provider_id, instrument, Timeframe.H1, as_of, MIDDLE_LOOKBACK)
        higher = await self._closed(provider_id, instrument, Timeframe.H4, as_of, HIGHER_LOOKBACK)
        rules = await self._rules.as_of(provider_id, instrument.id, as_of)
        if setup is None or middle is None or higher is None or rules is None:
            return SignalOutcome(Action.NO_TRADE, None, False, ("not enough data",))
        decision = evaluate(setup, middle, higher, rules.tick_size, self._parameters)
        if decision.proposal is None or decision.setup_atr is None:
            return SignalOutcome(decision.action, None, False, decision.reasons)
        return await self._assess(
            provider_id, instrument, as_of, account, rules, decision.proposal,
            decision.setup_atr, decision.reasons,
        )  # fmt: skip

    async def _assess(
        self,
        provider_id: int,
        instrument: Instrument,
        as_of: datetime,
        account: Account,
        rules: InstrumentRules,
        proposal: TradeProposal,
        setup_atr: Decimal,
        reasons: tuple[str, ...],
    ) -> SignalOutcome:
        now = self._clock.now()
        book = await self._snapshots.latest_book(provider_id, instrument.id, now)
        minutes = await self._closed(provider_id, instrument, Timeframe.M1, now, MINUTE_LOOKBACK)
        if book is None or minutes is None:
            return SignalOutcome(Action.NO_TRADE, None, False, ("no recent book",))
        book_minute, bid, ask = book
        minute_atr = Decimal(str(float(atr(minutes)[-1])))
        if minute_atr.is_nan():
            minute_atr = Decimal(0)
        slippage = max(SLIPPAGE_TICKS * rules.tick_size, SLIPPAGE_ATR_SHARE * minute_atr)
        funding = await self._market.funding_between(
            provider_id, instrument.id, now - timedelta(days=2), now
        )
        rate = funding[-1][1] if funding else Decimal(0)
        fees = await self._signals.fee_rates(provider_id, instrument.instrument_type.value, as_of)
        unresolved = await self._gaps.list(
            provider_id=provider_id, instrument_id=instrument.id, states=("detected", "repairing")
        )
        day_start = Timeframe.D1.floor(now)
        state = await self._paper.account_state(account.id, account.starting_balance, day_start)
        market = MarketState(
            bid=bid,
            ask=ask,
            entry_slippage=slippage,
            stop_slippage=slippage,
            setup_atr=setup_atr,
            funding_rate=rate,
            funding_intervals=HOLD_FUNDING_INTERVALS,
            data_age_seconds=int((now - book_minute).total_seconds()),
            has_open_gaps=bool(unresolved),
        )
        key = dedupe_key(
            account.id, instrument.id, proposal.side, Timeframe.M15, proposal.entry, setup_atr
        )
        request = RiskRequest(
            proposal=proposal,
            account=state,
            market=market,
            instrument=instrument,
            rules=rules,
            fees=fees,
            profile=account.profile,
            duplicate_active=await self._signals.is_active(account.id, key),
        )
        assessment = assess(request)
        quality = self._quality(assessment.sizing)
        strategy = await self._signals.ensure_strategy(
            STRATEGY_NAME, STRATEGY_VERSION, self._parameters.as_dict()
        )
        half_spread = (ask - bid) / 2
        recommendation = await self._signals.record(
            NewRecommendation(
                strategy_id=strategy,
                account=account,
                provider_id=provider_id,
                instrument_id=instrument.id,
                timeframe=Timeframe.M15,
                proposal=proposal,
                assessment=assessment,
                market_price=(bid + ask) / 2,
                equity=state.equity,
                dedupe_key=key,
                quality_score=Decimal(str(quality)),
                data_reliability=Decimal(100 if not unresolved else 50),
                technical_explanation="; ".join(reasons),
                evidence=reasons,
                conflicting=(),
                data_as_of=as_of,
                created_at=now,
                expires_at=now + Timeframe.M15.delta * (proposal.expiry_candles or 1),
                risk_inputs={
                    "half_spread": half_spread,
                    "entry_slippage": slippage,
                    "stop_slippage": slippage,
                    "taker_fee": fees.entry if fees else None,
                    "maker_fee": MAKER_FEE_FALLBACK,
                    "tick": rules.tick_size,
                    "lot_step": rules.lot_step,
                },
            )
        )
        if assessment.approved and assessment.sizing is not None:
            await self._paper.open_position(
                account.id, recommendation, instrument.id, proposal.side, assessment.sizing.quantity
            )
        action = Action.BUY if proposal.side.sign > 0 else Action.SELL
        log.info(
            "signal_recorded",
            action=action.value,
            approved=assessment.approved,
            codes=[c.value for c in assessment.codes],
        )
        return SignalOutcome(
            action, recommendation, assessment.approved, tuple(c.value for c in assessment.codes)
        )

    @staticmethod
    def _quality(sizing: Sizing | None) -> float:
        """The baseline only fires when these hold, so most evidence is already fixed at 1."""
        reward = 0.0
        if sizing is not None:
            reward = min(float(sizing.weighted_reward_risk) / 4, 1.0)
        return score_setup(
            SetupEvidence(
                timeframe_alignment=1.0,
                market_structure=1.0,
                momentum=0.5,
                volume=0.5,
                entry_quality=0.5,
                reward_risk=max(reward, 0.0),
                volatility=0.5,
            )
        ).score
