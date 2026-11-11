"""Turn a closed setup candle into a risk-checked signal.

Every proposal passes through the risk engine, and a rejection is stored with its reasons.
The live paper loop runs the 1H pattern breakout (docs/27) at each 1H close and the daily
trend (docs/29) at each daily close, which also tightens the trend's trailing stops (D039).
The demo bot runs the 15M rule baseline in its own account and enters at the live price (D044).
The money plan runs every strategy on every coin in one account, and signals that arrive at
the same close share its room by tested evidence (D045).
Each strategy holds at most one position per coin and account, as in its backtest.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Any, Final, Protocol
from uuid import UUID

import structlog

from trading_intel.core.clock import Clock
from trading_intel.database.repositories.candles import CandleRepository
from trading_intel.database.repositories.exchange import ExchangeRepository
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
from trading_intel.domain.signals import Action, EntryType, Side
from trading_intel.execution.orders import TradePlan, price_limits
from trading_intel.execution.trader import Budget, FuturesTrader, PendingEntry, Position
from trading_intel.risk_management.allocation import Claim, split
from trading_intel.risk_management.calculators.linear import (
    loss_floor,
    remaining_daily_budget,
    remaining_open_risk,
)
from trading_intel.risk_management.engine import assess
from trading_intel.risk_management.models import (
    AccountState,
    MarketState,
    RiskAssessment,
    RiskProfile,
    RiskRequest,
    Sizing,
    TradeProposal,
)
from trading_intel.risk_management.rejections import RejectionCode
from trading_intel.technical_analysis.series import CandleSeries
from trading_intel.technical_analysis.volatility import atr
from trading_intel.trade_signals.baseline import (
    STRATEGY_NAME,
    STRATEGY_VERSION,
    BaselineDecision,
    BaselineParameters,
    evaluate,
)
from trading_intel.trade_signals.fvg_choch_strategy import STRATEGY_NAME as FVG_NAME
from trading_intel.trade_signals.fvg_choch_strategy import STRATEGY_VERSION as FVG_VERSION
from trading_intel.trade_signals.fvg_choch_strategy import FvgChochStrategy
from trading_intel.trade_signals.lifecycle import dedupe_key
from trading_intel.trade_signals.news_move_strategy import STRATEGY_NAME as NEWS_MOVE_NAME
from trading_intel.trade_signals.news_move_strategy import (
    STRATEGY_VERSION as NEWS_MOVE_VERSION,
)
from trading_intel.trade_signals.news_move_strategy import NewsMoveStrategy
from trading_intel.trade_signals.pattern_strategy import STRATEGY_NAME as PATTERN_NAME
from trading_intel.trade_signals.pattern_strategy import STRATEGY_VERSION as PATTERN_VERSION
from trading_intel.trade_signals.pattern_strategy import PatternStrategy
from trading_intel.trade_signals.portfolio import LEFT_OUT, due, share_of
from trading_intel.trade_signals.quality import SetupEvidence, score_setup
from trading_intel.trade_signals.signal_score import (
    FUNDING_HISTORY,
    VOLUME_CANDLES,
    Conditions,
    FundingView,
    LongTermTrend,
    VolumeView,
)
from trading_intel.trade_signals.signal_score import TREND_DAYS as SCORE_DAYS
from trading_intel.trade_signals.trend_strategy import STRATEGY_NAME as TREND_NAME
from trading_intel.trade_signals.trend_strategy import STRATEGY_VERSION as TREND_VERSION
from trading_intel.trade_signals.trend_strategy import DailyTrendStrategy

log = structlog.get_logger(__name__)

SETUP_LOOKBACK: Final = 400
MIDDLE_LOOKBACK: Final = 200
HIGHER_LOOKBACK: Final = 150
MINUTE_LOOKBACK: Final = 30
SLIPPAGE_TICKS: Final = 2
SLIPPAGE_ATR_SHARE: Final = Decimal("0.05")
HOLD_FUNDING_INTERVALS: Final = 1
MAKER_FEE_FALLBACK: Final = Decimal("0.0002")
# History each live strategy reads at a close, as the dashboard's analysis does.
PATTERN_HOURS: Final = 1440
# Enough 1H candles for Wilder's ATR(14) to settle before the move (docs/40).
NEWS_MOVE_HOURS: Final = 200
PATTERN_FOURS: Final = 1200
PATTERN_DAYS: Final = 3000
TREND_DAYS: Final = 1000
# About 35 days of 15M candles and 100 days of 4H candles, as registered in docs/35.
FVG_QUARTERS: Final = 3360
FVG_FOURS: Final = 600
NO_DATA: Final = ("not enough data",)
ZERO: Final = Decimal(0)
# Share of Binance's available balance the risk engine may use as margin (D048). The rest
# covers fees and price moves before the entry fills.
MARGIN_USE: Final = Decimal("0.95")


@dataclass(frozen=True)
class StrategyIdentity:
    """The strategy a signal came from, stored with it."""

    name: str
    version: int
    parameters: dict[str, Any]


@dataclass(frozen=True)
class SignalOutcome:
    action: Action
    recommendation_id: UUID | None
    approved: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class Setup:
    """One strategy's decision on one coin at a close, before any risk check."""

    instrument: Instrument
    rules: InstrumentRules
    decision: BaselineDecision
    identity: StrategyIdentity
    timeframe: Timeframe
    instant: bool = False


@dataclass(frozen=True)
class Prepared:
    """A risk request with the live context its record needs."""

    request: RiskRequest
    now: datetime
    bid: Decimal
    ask: Decimal
    slippage: Decimal
    key: str
    unresolved: bool
    instant: bool


def _claims(
    ready: Sequence[tuple[Setup, Prepared, str]], state: AccountState, profile: RiskProfile
) -> list[Claim]:
    """What each signal asks for, sized alone as if the account had all its room.

    A signal refused alone for any reason but its size is no claim: the risk engine refuses
    it again with that reason. One too large alone is a claim, and the split shrinks it.
    """
    empty = state.model_copy(
        update={"open_positions": 0, "gross_exposure": ZERO, "open_risk": ZERO}
    )
    claims: list[Claim] = []
    for setup, prepared, key in ready:
        alone = assess(prepared.request.model_copy(update={"account": empty}))
        sizing = alone.sizing
        if set(alone.codes) - {RejectionCode.EXPOSURE_EXCEEDED} or sizing is None:
            continue
        if sizing.risk_per_unit <= 0:
            continue
        share = prepared.request.proposal.risk_share
        risk = state.equity * profile.max_risk_fraction * share
        unit = sizing.entry_fill * setup.instrument.contract_multiplier
        claims.append(Claim(key, share, risk, risk / sizing.risk_per_unit * unit))
    return claims


def _room(state: AccountState, profile: RiskProfile) -> tuple[Decimal, Decimal, int]:
    """Risk the account may still take today, its unused exposure and its free slots."""
    risk = remaining_daily_budget(state, profile)
    open_room = remaining_open_risk(state, profile)
    if open_room is not None:
        risk = min(risk, open_room)
    exposure = state.equity * profile.max_total_exposure_fraction - state.gross_exposure
    return risk, exposure, profile.max_open_positions - state.open_positions


class NewsEvidence(Protocol):
    """What the news said about a coin at a moment, and whether it agrees with a side (D055).

    Provided by the news module through the entrypoints, which this module never imports. It
    is stored beside every signal, and it confirms the news move strategy's moves (D056). It
    never starts a trade: that strategy's price move comes first.
    """

    async def alignment(
        self, instrument_id: int, side: Side, at: datetime
    ) -> tuple[str, dict[str, Any]]: ...


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
        bitcoin: Instrument | None = None,
        news: NewsEvidence | None = None,
    ) -> None:
        """`bitcoin` is the perpetual whose trend the signal score reads for other coins.

        `news` gives what the news said about a coin, stored beside each signal (D055). Only
        the news move strategy acts on it, to confirm a move (D056). Without it, signals record
        news as unavailable and that strategy never trades.
        """
        self._candles = candles
        self._snapshots = snapshots
        self._market = market
        self._gaps = gaps
        self._rules = rules
        self._signals = signals
        self._paper = paper
        self._news = news
        self._clock = clock
        self._parameters = parameters or BaselineParameters()
        self._bitcoin = bitcoin

    async def _closed(
        self, provider_id: int, instrument: Instrument, timeframe: Timeframe, at: datetime, n: int
    ) -> CandleSeries | None:
        rows = await self._candles.for_analysis(provider_id, instrument.id, timeframe, at, n)
        return CandleSeries.of(rows) if rows else None

    async def baseline_setup(
        self, provider_id: int, instrument: Instrument, as_of: datetime, *, instant: bool = False
    ) -> Setup | None:
        """The 15M rule baseline's decision at a 15M close."""
        setup = await self._closed(provider_id, instrument, Timeframe.M15, as_of, SETUP_LOOKBACK)
        middle = await self._closed(provider_id, instrument, Timeframe.H1, as_of, MIDDLE_LOOKBACK)
        higher = await self._closed(provider_id, instrument, Timeframe.H4, as_of, HIGHER_LOOKBACK)
        rules = await self._rules.as_of(provider_id, instrument.id, as_of)
        if setup is None or middle is None or higher is None or rules is None:
            return None
        decision = evaluate(setup, middle, higher, rules.tick_size, self._parameters)
        identity = StrategyIdentity(STRATEGY_NAME, STRATEGY_VERSION, self._parameters.as_dict())
        return Setup(instrument, rules, decision, identity, Timeframe.M15, instant)

    async def pattern_setup(
        self, provider_id: int, instrument: Instrument, as_of: datetime
    ) -> Setup | None:
        """The 1H pattern breakout's decision at a 1H close."""
        hours = await self._candles.for_analysis(
            provider_id, instrument.id, Timeframe.H1, as_of, PATTERN_HOURS
        )
        fours = await self._candles.for_analysis(
            provider_id, instrument.id, Timeframe.H4, as_of, PATTERN_FOURS
        )
        days = await self._candles.for_analysis(
            provider_id, instrument.id, Timeframe.D1, as_of, PATTERN_DAYS
        )
        rules = await self._rules.as_of(provider_id, instrument.id, as_of)
        if not hours or not fours or not days or rules is None:
            return None
        strategy = PatternStrategy(hours, fours, days, rules.tick_size)
        identity = StrategyIdentity(PATTERN_NAME, PATTERN_VERSION, strategy.parameters.as_dict())
        decision = strategy.decide(hours[-1].close_time)
        return Setup(instrument, rules, decision, identity, Timeframe.H1)

    async def news_move_setup(
        self, provider_id: int, instrument: Instrument, as_of: datetime
    ) -> Setup | None:
        """The news move strategy at a 1H close (docs/40, D056): Python finds a strong move,
        and it becomes a trade only if the coin's news agrees with it."""
        hours = await self._candles.for_analysis(
            provider_id, instrument.id, Timeframe.H1, as_of, NEWS_MOVE_HOURS
        )
        rules = await self._rules.as_of(provider_id, instrument.id, as_of)
        if not hours or rules is None:
            return None
        strategy = NewsMoveStrategy(hours, rules.tick_size)
        identity = StrategyIdentity(
            NEWS_MOVE_NAME, NEWS_MOVE_VERSION, strategy.parameters.as_dict()
        )
        decision = strategy.decide(hours[-1].close_time)
        if decision.proposal is not None:
            decision = await self._news_confirms(instrument, decision)
        return Setup(instrument, rules, decision, identity, Timeframe.H1)

    async def _news_confirms(
        self, instrument: Instrument, decision: BaselineDecision
    ) -> BaselineDecision:
        """A move stays a trade only if the coin's news reading agrees with its side (D056).

        A neutral, opposite or failed reading means no trade, so news can confirm a move
        Python found but never start one.
        """
        assert decision.proposal is not None
        refused = None
        if self._news is None:
            refused = "no news reading"
        else:
            try:
                found, context = await self._news.alignment(
                    instrument.id, decision.proposal.side, decision.as_of
                )
            except Exception as error:
                log.error(
                    "news_alignment_failed",
                    instrument=instrument.symbol,
                    error=type(error).__name__,
                    detail=str(error)[:300],
                )
                refused = "the news reading failed"
            else:
                said = f"news is {context.get('direction', 'unknown')}"
                if found != "aligned":
                    refused = f"{said}, not with the move"
                else:
                    return replace(decision, reasons=(*decision.reasons, f"{said}, with the move"))
        return BaselineDecision(Action.NO_TRADE, decision.as_of, (*decision.reasons, refused))

    async def fvg_setup(
        self, provider_id: int, instrument: Instrument, as_of: datetime
    ) -> Setup | None:
        """The 4H gap and 15M CHoCH strategy's decision at a 15M close (docs/35)."""
        quarters = await self._candles.for_analysis(
            provider_id, instrument.id, Timeframe.M15, as_of, FVG_QUARTERS
        )
        fours = await self._candles.for_analysis(
            provider_id, instrument.id, Timeframe.H4, as_of, FVG_FOURS
        )
        rules = await self._rules.as_of(provider_id, instrument.id, as_of)
        if not quarters or not fours or rules is None:
            return None
        strategy = FvgChochStrategy(quarters, fours, rules.tick_size)
        identity = StrategyIdentity(FVG_NAME, FVG_VERSION, strategy.parameters.as_dict())
        decision = strategy.decide(quarters[-1].close_time)
        return Setup(instrument, rules, decision, identity, Timeframe.M15)

    async def trend_setup(
        self, provider_id: int, instrument: Instrument, as_of: datetime
    ) -> Setup | None:
        """The daily trend's decision at a daily close."""
        days = await self._candles.for_analysis(
            provider_id, instrument.id, Timeframe.D1, as_of, TREND_DAYS
        )
        rules = await self._rules.as_of(provider_id, instrument.id, as_of)
        if not days or rules is None:
            return None
        strategy = DailyTrendStrategy(days, rules.tick_size)
        identity = StrategyIdentity(TREND_NAME, TREND_VERSION, strategy.parameters.as_dict())
        decision = strategy.decide(days[-1].close_time)
        return Setup(instrument, rules, decision, identity, Timeframe.D1)

    async def evaluate(
        self,
        provider_id: int,
        instrument: Instrument,
        as_of: datetime,
        account: Account,
        *,
        instant: bool = False,
    ) -> SignalOutcome:
        """The 15M rule baseline at a 15M close. `instant` enters at the live price (D044)."""
        setup = await self.baseline_setup(provider_id, instrument, as_of, instant=instant)
        return await self._submit_setup(provider_id, as_of, account, setup)

    async def evaluate_pattern(
        self, provider_id: int, instrument: Instrument, as_of: datetime, account: Account
    ) -> SignalOutcome:
        """The 1H pattern breakout strategy at a 1H close."""
        setup = await self.pattern_setup(provider_id, instrument, as_of)
        return await self._submit_setup(provider_id, as_of, account, setup)

    async def evaluate_trend(
        self, provider_id: int, instrument: Instrument, as_of: datetime, account: Account
    ) -> SignalOutcome:
        """The daily trend strategy at a daily close."""
        setup = await self.trend_setup(provider_id, instrument, as_of)
        return await self._submit_setup(provider_id, as_of, account, setup)

    async def trail_stops(self, provider_id: int, instrument: Instrument, as_of: datetime) -> int:
        """Tighten open daily trend positions to the 10-day extreme. Returns how many moved."""
        trades = [
            trade
            for trade in await self._paper.active(provider_id, instrument.id)
            if trade.strategy == TREND_NAME
        ]
        days = await self._candles.for_analysis(
            provider_id, instrument.id, Timeframe.D1, as_of, TREND_DAYS
        )
        rules = await self._rules.as_of(provider_id, instrument.id, as_of)
        if not trades or not days or rules is None:
            return 0
        strategy = DailyTrendStrategy(days, rules.tick_size)
        moment = days[-1].close_time
        reason = f"{strategy.parameters.exit_days}-day trailing exit"
        moved = 0
        for trade in trades:
            current = trade.stop_moves[-1][1] if trade.stop_moves else trade.stop
            level = strategy.trailing_stop(moment, trade.side, current)
            if level is not None and await self._paper.record_stop_move(
                trade.position_id, moment, level, reason
            ):
                moved += 1
        return moved

    async def trail_exchange_stop(
        self,
        provider_id: int,
        instrument: Instrument,
        as_of: datetime,
        account: Account,
        trader: FuturesTrader,
        orders: ExchangeRepository,
    ) -> bool:
        """The same trail for a daily trend position on Binance demo trading (D039, D048).

        Binance holds the stop, so the move replaces it there, and the stop it then holds is
        recorded for the minute check. Until 2026-11-11 only paper stops trailed, and a
        Binance trend trade kept its first stop with no other exit.
        """
        symbol = instrument.symbol
        trade = await orders.latest_trade(account.id, symbol)
        stop = (await orders.stops(account.id)).get(symbol)
        if trade is None or trade.strategy != TREND_NAME or stop is None or stop[1] != trade.key:
            return False
        position = (await trader.view()).positions.get(symbol)
        days = await self._candles.for_analysis(
            provider_id, instrument.id, Timeframe.D1, as_of, TREND_DAYS
        )
        rules = await self._rules.as_of(provider_id, instrument.id, as_of)
        if position is None or not days or rules is None:
            return False
        moment = days[-1].close_time
        level = DailyTrendStrategy(days, rules.tick_size).trailing_stop(
            moment, position.side, stop[0]
        )
        if level is None:
            return False
        move = await trader.move_stop(symbol, level, f"{trade.key}:trail:{moment.date()}")
        for record in move.records:
            held = move.held is not None and record.client_id == move.held[1]
            await orders.record(
                account.id, trade.recommendation_id, record,
                trade_key=trade.key if held else None,
                stop_price=move.held[0] if held and move.held else None,
            )  # fmt: skip
        log.info(
            "exchange_stop_trailed",
            instrument=symbol,
            moved=move.moved,
            stop=str(stop[0]),
            level=str(level),
            held=None if move.held is None else str(move.held[0]),
        )
        return move.moved

    async def plan_setups(
        self, provider_id: int, instruments: Sequence[Instrument], close_time: datetime
    ) -> tuple[list[Setup], list[str]]:
        """Every due strategy's decision on every coin at this close, for the money plan.

        A coin whose candle for this close is not stored yet is listed as missing. It is never
        decided on the candle before, which would trade an old close as if it were new.
        """
        setups: list[Setup] = []
        missing: list[str] = []
        for timeframe in due(close_time):
            for instrument in instruments:
                for setup in await self._setups_at(timeframe, provider_id, instrument, close_time):
                    if setup is None or setup.decision.as_of != close_time:
                        missing.append(f"{instrument.symbol} {timeframe.value}")
                        continue
                    setups.append(setup)
        return setups, missing

    async def _setups_at(
        self, timeframe: Timeframe, provider_id: int, instrument: Instrument, close_time: datetime
    ) -> list[Setup | None]:
        match timeframe:
            case Timeframe.M15:
                return [
                    await self.baseline_setup(provider_id, instrument, close_time, instant=True),
                    await self.fvg_setup(provider_id, instrument, close_time),
                ]
            case Timeframe.H1:
                return [
                    await self.pattern_setup(provider_id, instrument, close_time),
                    await self.news_move_setup(provider_id, instrument, close_time),
                ]
            case _:
                return [await self.trend_setup(provider_id, instrument, close_time)]

    async def run_plan(
        self, provider_id: int, as_of: datetime, account: Account, setups: Sequence[Setup]
    ) -> list[SignalOutcome]:
        """The money plan (D045): signals from one close share the account's room.

        Each signal asks for its strategy's evidence share of the 1% risk. The strongest
        evidence is served first and equal evidence splits what is left. The risk engine still
        decides every trade, seeing the trades approved before it in the same close.
        """
        state = await self._paper.account_state(
            account.id, account.starting_balance, Timeframe.D1.floor(self._clock.now())
        )
        outcomes: list[SignalOutcome] = []
        ready: list[tuple[Setup, Prepared, str]] = []
        for setup in setups:
            decision, name = setup.decision, setup.identity.name
            if decision.proposal is None or decision.setup_atr is None:
                outcomes.append(SignalOutcome(decision.action, None, False, decision.reasons))
                continue
            if (name, setup.instrument.symbol) in LEFT_OUT:
                reason = "this strategy lost on this coin in the study (docs/33)"
                outcomes.append(SignalOutcome(Action.NO_TRADE, None, False, (reason,)))
                continue
            holding = await self._paper.active(provider_id, setup.instrument.id)
            if any(t.account_id == account.id and t.strategy == name for t in holding):
                reason = "a position from this strategy is open"
                outcomes.append(SignalOutcome(Action.NO_TRADE, None, False, (reason,)))
                continue
            proposal = decision.proposal.model_copy(update={"risk_share": share_of(name)})
            prepared = await self._prepare(
                provider_id, setup.instrument, as_of, account, setup.rules, proposal,
                decision.setup_atr, timeframe=setup.timeframe, instant=setup.instant,
                state=state,
            )  # fmt: skip
            if prepared is None:
                outcomes.append(SignalOutcome(Action.NO_TRADE, None, False, ("no recent book",)))
                continue
            ready.append((setup, prepared, f"{name}:{setup.instrument.symbol}"))
        shares = split(_claims(ready, state, account.profile), *_room(state, account.profile))
        ready.sort(key=lambda item: (-item[1].request.proposal.risk_share, item[2]))
        for setup, prepared, key in ready:
            wish = prepared.request.proposal.risk_share
            final = shares.get(key, wish)
            proposal = prepared.request.proposal.model_copy(update={"risk_share": final})
            request = prepared.request.model_copy(update={"proposal": proposal, "account": state})
            assessment = assess(request)
            outcome = await self._record(
                provider_id, setup.instrument, as_of, account, setup.rules,
                replace(prepared, request=request), assessment, setup.decision.reasons,
                setup.identity, setup.timeframe,
                plan={"evidence_share": wish, "risk_share": final},
            )  # fmt: skip
            outcomes.append(outcome)
            sizing = assessment.sizing
            if assessment.approved and sizing is not None:
                state = state.model_copy(
                    update={
                        "open_positions": state.open_positions + 1,
                        "gross_exposure": state.gross_exposure + sizing.notional,
                        "open_risk": state.open_risk + sizing.max_account_risk,
                    }
                )
        return outcomes

    async def run_exchange_plan(
        self,
        provider_id: int,
        as_of: datetime,
        account: Account,
        setups: Sequence[Setup],
        trader: FuturesTrader,
        orders: ExchangeRepository,
    ) -> list[SignalOutcome]:
        """The money plan on Binance demo trading (D048), with Binance's account as the truth.

        Each signal asks for its strategy's evidence share of the profile's risk per trade,
        strongest first, as in the paper plan. Binance holds one position per coin in one-way
        mode, so a coin with a position or a waiting limit entry takes no new signal. The risk
        engine sizes each trade at the lowest leverage whose margin fits, up to the profile's
        maximum, and only an approved trade is sent: a market or limit entry, a stop for the
        whole position, and a take-profit per target (D054). Once the account's loss stop is
        reached, nothing trades until the owner sets a new profile version (D053).
        """
        view = await trader.view()
        if view.equity <= 0:
            return [SignalOutcome(Action.NO_TRADE, None, False, ("no equity on Binance demo",))]
        today = Timeframe.D1.floor(self._clock.now()).date()
        day_start = await orders.day_start(account.id, today, view.equity)
        baseline = await orders.baseline(account.id) or day_start
        # The account's starting balance is its budget: Binance's test funds are not all used.
        budget = Budget.of(view, account.starting_balance, baseline, day_start)
        if budget.equity <= 0 or budget.day_start_equity <= 0:
            return [SignalOutcome(Action.NO_TRADE, None, False, ("the budget is used up",))]
        # The loss stop holds until the owner decides again, as a new profile version (D053).
        reached = await orders.loss_stop(account.id, account.risk_profile_id)
        floor = loss_floor(account.starting_balance, account.profile)
        if reached is None and floor is not None and budget.equity <= floor:
            reached = self._clock.now()
            await orders.record_loss_stop(
                account.id, account.risk_profile_id, reached, budget.equity, floor
            )
            log.warning("loss_stop_reached", equity=str(budget.equity), floor=str(floor))
        if reached is not None:
            stopped = (
                f"stopped by its loss stop at {reached:%Y-%m-%d %H:%M} UTC, until the owner decides"
            )
            return [SignalOutcome(Action.NO_TRADE, None, False, (stopped,))]
        stops = await orders.stops(account.id)
        # A limit entry waiting on Binance counts as a trade: its coin, size and risk (D054).
        state = AccountState(
            equity=budget.equity,
            day_start_equity=budget.day_start_equity,
            open_positions=len(set(view.positions) | set(view.pending)),
            gross_exposure=sum((p.notional for p in view.positions.values()), ZERO)
            + sum((e.notional for e in view.pending.values()), ZERO),
            open_risk=sum((_risk_at_stop(p, stops.get(s)) for s, p in view.positions.items()), ZERO)
            + sum((_entry_risk(e, stops.get(s)) for s, e in view.pending.items()), ZERO),
            available_margin=budget.available * MARGIN_USE,
            start_equity=account.starting_balance,
        )
        taken = set(view.positions)
        waiting = set(view.pending) - taken
        outcomes: list[SignalOutcome] = []
        ready = sorted(
            (s for s in setups if s.decision.proposal is not None and s.decision.setup_atr),
            key=lambda s: (-share_of(s.identity.name), s.identity.name, s.instrument.symbol),
        )
        for setup in ready:
            name, symbol = setup.identity.name, setup.instrument.symbol
            proposal = setup.decision.proposal
            assert proposal is not None
            refused = (
                "this strategy lost on this coin in the study (docs/33)"
                if (name, symbol) in LEFT_OUT
                else "a position on this coin is open on Binance"
                if symbol in taken
                else "a limit entry on this coin is waiting on Binance"
                if symbol in waiting
                else "only market and limit entries are sent to Binance"
                if proposal.entry_type is EntryType.STOP
                else None
            )
            if refused:
                outcomes.append(SignalOutcome(Action.NO_TRADE, None, False, (refused,)))
                continue
            share = share_of(name)
            chosen = await self._at_lowest_leverage(
                provider_id,
                setup,
                as_of,
                account,
                proposal.model_copy(update={"risk_share": share}),
                state,
            )
            if chosen is None:
                outcomes.append(SignalOutcome(Action.NO_TRADE, None, False, ("no recent book",)))
                continue
            prepared, assessment = chosen
            leverage = int(prepared.request.proposal.leverage)
            outcome = await self._record(
                provider_id, setup.instrument, as_of, account, setup.rules, prepared, assessment,
                setup.decision.reasons, setup.identity, setup.timeframe,
                plan={"evidence_share": share, "risk_share": share, "leverage": Decimal(leverage)},
                open_paper=False,
            )  # fmt: skip
            outcomes.append(outcome)
            sizing = assessment.sizing
            if not assessment.approved or sizing is None or outcome.recommendation_id is None:
                continue
            sent = prepared.request.proposal
            lowest, highest = price_limits(setup.rules.raw)
            # Binance cancels a limit entry itself when the signal expires.
            expires = prepared.now + setup.timeframe.delta * (sent.expiry_candles or 1)
            is_limit = sent.entry_type is EntryType.LIMIT
            plan = TradePlan(
                key=prepared.key,
                symbol=symbol,
                side=sent.side,
                leverage=leverage,
                quantity=sizing.quantity,
                stop=sent.stop,
                targets=sent.targets,
                allocation=sizing.allocation,
                lot_step=setup.rules.lot_step,
                min_qty=setup.rules.min_qty,
                min_price=lowest,
                max_price=highest,
                limit=sent.entry if is_limit else None,
                good_till_ms=int(expires.timestamp() * 1000) if is_limit else None,
            )
            result = await trader.open_trade(plan)
            for record in result.records:
                keeps_stop = record.kind in ("entry", "stop")
                await orders.record(
                    account.id, outcome.recommendation_id, record,
                    trade_key=plan.key if keeps_stop else None,
                    stop_price=plan.stop if keeps_stop else None,
                )  # fmt: skip
            log.info(
                "exchange_trade",
                instrument=symbol,
                strategy=name,
                filled=str(result.filled),
                protected=result.protected,
                waiting=result.waiting,
                leverage=leverage,
            )
            if result.filled > 0 or result.waiting:
                (waiting if result.waiting else taken).add(symbol)
                state = state.model_copy(
                    update={
                        "open_positions": state.open_positions + 1,
                        "gross_exposure": state.gross_exposure + sizing.notional,
                        "open_risk": state.open_risk + sizing.max_account_risk,
                        "available_margin": max(
                            (state.available_margin or ZERO) - sizing.margin, ZERO
                        ),
                    }
                )
        return outcomes

    async def _at_lowest_leverage(
        self,
        provider_id: int,
        setup: Setup,
        as_of: datetime,
        account: Account,
        proposal: TradeProposal,
        state: AccountState,
    ) -> tuple[Prepared, RiskAssessment] | None:
        """Leverage 1, then 2, up to the profile's maximum, until the margin fits.

        Leverage never changes what the stop loses, only the margin held and how near
        liquidation sits, which the risk engine checks at every step.
        """
        assert setup.decision.setup_atr is not None
        prepared = await self._prepare(
            provider_id, setup.instrument, as_of, account, setup.rules,
            proposal.model_copy(update={"leverage": Decimal(1)}), setup.decision.setup_atr,
            timeframe=setup.timeframe, instant=True, state=state,
        )  # fmt: skip
        if prepared is None:
            return None
        assessment = assess(prepared.request)
        leverage = 1
        while (
            RejectionCode.MARGIN_INSUFFICIENT in assessment.codes
            and leverage < account.profile.max_leverage
        ):
            leverage += 1
            raised = prepared.request.proposal.model_copy(update={"leverage": Decimal(leverage)})
            prepared = replace(
                prepared, request=prepared.request.model_copy(update={"proposal": raised})
            )
            assessment = assess(prepared.request)
        return prepared, assessment

    async def _submit_setup(
        self, provider_id: int, as_of: datetime, account: Account, setup: Setup | None
    ) -> SignalOutcome:
        if setup is None:
            return SignalOutcome(Action.NO_TRADE, None, False, NO_DATA)
        return await self._submit(
            provider_id, setup.instrument, as_of, account, setup.rules, setup.decision,
            setup.identity, setup.timeframe, instant=setup.instant,
        )  # fmt: skip

    async def _submit(
        self,
        provider_id: int,
        instrument: Instrument,
        as_of: datetime,
        account: Account,
        rules: InstrumentRules,
        decision: BaselineDecision,
        identity: StrategyIdentity,
        timeframe: Timeframe,
        *,
        instant: bool = False,
    ) -> SignalOutcome:
        if decision.proposal is None or decision.setup_atr is None:
            return SignalOutcome(decision.action, None, False, decision.reasons)
        holding = await self._paper.active(provider_id, instrument.id)
        if any(t.account_id == account.id and t.strategy == identity.name for t in holding):
            # One position per coin, strategy and account, as in the backtests.
            return SignalOutcome(
                Action.NO_TRADE, None, False, ("a position from this strategy is open",)
            )
        return await self._assess(
            provider_id, instrument, as_of, account, rules, decision.proposal,
            decision.setup_atr, decision.reasons, strategy=identity, timeframe=timeframe,
            instant=instant,
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
        *,
        strategy: StrategyIdentity | None = None,
        timeframe: Timeframe = Timeframe.M15,
        instant: bool = False,
    ) -> SignalOutcome:
        identity = strategy or StrategyIdentity(
            STRATEGY_NAME, STRATEGY_VERSION, self._parameters.as_dict()
        )
        prepared = await self._prepare(
            provider_id, instrument, as_of, account, rules, proposal, setup_atr,
            timeframe=timeframe, instant=instant,
        )  # fmt: skip
        if prepared is None:
            return SignalOutcome(Action.NO_TRADE, None, False, ("no recent book",))
        return await self._record(
            provider_id, instrument, as_of, account, rules, prepared, assess(prepared.request),
            reasons, identity, timeframe,
        )  # fmt: skip

    async def _prepare(
        self,
        provider_id: int,
        instrument: Instrument,
        as_of: datetime,
        account: Account,
        rules: InstrumentRules,
        proposal: TradeProposal,
        setup_atr: Decimal,
        *,
        timeframe: Timeframe,
        instant: bool,
        state: AccountState | None = None,
    ) -> Prepared | None:
        """The risk request for a proposal, with the live book, costs and account."""
        now = self._clock.now()
        book = await self._snapshots.latest_book(provider_id, instrument.id, now)
        minutes = await self._closed(provider_id, instrument, Timeframe.M1, now, MINUTE_LOOKBACK)
        if book is None or minutes is None:
            return None
        book_minute, bid, ask = book
        # A minute row holds the last bid and ask seen in that minute, so it is as fresh as the
        # minute's end. Its start is always over a minute old, which once made every live
        # signal stale (2026-11-07).
        book_seen = min(now, Timeframe.M1.close_time(book_minute))
        minute_atr = Decimal(str(float(atr(minutes)[-1])))
        if minute_atr.is_nan():
            minute_atr = Decimal(0)
        slippage = max(SLIPPAGE_TICKS * rules.tick_size, SLIPPAGE_ATR_SHARE * minute_atr)
        instant = instant and proposal.entry_type is EntryType.MARKET
        if instant:
            # The bot enters now, so the risk engine sizes it from the live mid, rounded against
            # the trade. It fills there plus half the spread and slippage (D044).
            proposal = proposal.model_copy(
                update={"entry": _against(proposal.side, (bid + ask) / 2, rules.tick_size)}
            )
        funding = await self._market.funding_between(
            provider_id, instrument.id, now - timedelta(days=2), now
        )
        rate = funding[-1][1] if funding else Decimal(0)
        fees = await self._signals.fee_rates(provider_id, instrument.instrument_type.value, as_of)
        unresolved = await self._gaps.list(
            provider_id=provider_id, instrument_id=instrument.id, states=("detected", "repairing")
        )
        if state is None:
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
            data_age_seconds=int((now - book_seen).total_seconds()),
            has_open_gaps=bool(unresolved),
        )
        key = dedupe_key(
            account.id, instrument.id, proposal.side, timeframe, proposal.entry, setup_atr
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
        return Prepared(request, now, bid, ask, slippage, key, bool(unresolved), instant)

    async def _record(
        self,
        provider_id: int,
        instrument: Instrument,
        as_of: datetime,
        account: Account,
        rules: InstrumentRules,
        prepared: Prepared,
        assessment: RiskAssessment,
        reasons: tuple[str, ...],
        identity: StrategyIdentity,
        timeframe: Timeframe,
        plan: dict[str, Decimal] | None = None,
        *,
        open_paper: bool = True,
    ) -> SignalOutcome:
        """Store the signal and its assessment, and open the paper position if approved.

        An exchange account opens nothing here: its trade goes to Binance (D048).
        """
        proposal, fees = prepared.request.proposal, prepared.request.fees
        quality = self._quality(assessment.sizing)
        score = await self._score_record(provider_id, instrument, timeframe, as_of, proposal.side)
        news, news_context = await self._news_record(instrument, as_of, proposal.side)
        strategy_id = await self._signals.ensure_strategy(
            identity.name, identity.version, identity.parameters
        )
        half_spread = (prepared.ask - prepared.bid) / 2
        taken: dict[str, Decimal] = {}
        if prepared.instant and assessment.sizing is not None:
            taken["entry_fill"] = assessment.sizing.entry_fill
        recommendation = await self._signals.record(
            NewRecommendation(
                strategy_id=strategy_id,
                account=account,
                provider_id=provider_id,
                instrument_id=instrument.id,
                timeframe=timeframe,
                proposal=proposal,
                assessment=assessment,
                market_price=(prepared.bid + prepared.ask) / 2,
                equity=prepared.request.account.equity,
                dedupe_key=prepared.key,
                quality_score=Decimal(str(quality)),
                data_reliability=Decimal(100 if not prepared.unresolved else 50),
                technical_explanation="; ".join(reasons),
                evidence=reasons,
                conflicting=(),
                data_as_of=as_of,
                created_at=prepared.now,
                expires_at=prepared.now + timeframe.delta * (proposal.expiry_candles or 1),
                risk_inputs={
                    "half_spread": half_spread,
                    "entry_slippage": prepared.slippage,
                    "stop_slippage": prepared.slippage,
                    "taker_fee": fees.entry if fees else None,
                    "maker_fee": MAKER_FEE_FALLBACK,
                    "tick": rules.tick_size,
                    "lot_step": rules.lot_step,
                    **taken,
                    **(plan or {}),
                },
                signal_score=score,
                news_alignment=news,
                news_context=news_context,
            )
        )
        if open_paper and assessment.approved and assessment.sizing is not None:
            await self._paper.open_position(
                account.id, recommendation, instrument.id, proposal.side, assessment.sizing.quantity
            )
        action = Action.BUY if proposal.side.sign > 0 else Action.SELL
        log.info(
            "signal_recorded",
            strategy=identity.name,
            instrument=instrument.symbol,
            action=action.value,
            approved=assessment.approved,
            codes=[c.value for c in assessment.codes],
        )
        return SignalOutcome(
            action, recommendation, assessment.approved, tuple(c.value for c in assessment.codes)
        )

    async def _news_record(
        self, instrument: Instrument, as_of: datetime, side: Side
    ) -> tuple[str, dict[str, Any] | None]:
        """What the news said at this close, after the risk engine has decided (D055).

        A failure here must not lose the signal, so it is logged and recorded as unavailable.
        """
        if self._news is None:
            return "unavailable", None
        try:
            return await self._news.alignment(instrument.id, side, as_of)
        except Exception as error:
            log.error(
                "news_alignment_failed",
                instrument=instrument.symbol,
                error=type(error).__name__,
                detail=str(error)[:300],
            )
            return "unavailable", None

    async def _score_record(
        self,
        provider_id: int,
        instrument: Instrument,
        timeframe: Timeframe,
        as_of: datetime,
        side: Side,
    ) -> dict[str, Any] | None:
        """The signal score's conditions at this close, stored as information only (D046).

        A failure here must not lose the signal, so it is logged and the score left empty.
        """
        try:
            conditions = await self._signal_score(provider_id, instrument, timeframe, as_of, side)
        except Exception as error:
            log.error(
                "signal_score_failed",
                instrument=instrument.symbol,
                error=type(error).__name__,
                detail=str(error)[:300],
            )
            return None
        return conditions.as_record()

    async def _signal_score(
        self,
        provider_id: int,
        instrument: Instrument,
        timeframe: Timeframe,
        as_of: datetime,
        side: Side,
    ) -> Conditions:
        """The four conditions of docs/34, read from what was stored by this close."""
        is_bitcoin = self._bitcoin is not None and instrument.id == self._bitcoin.id
        own = await self._long_term_trend(provider_id, instrument, as_of)
        market = None
        if self._bitcoin is not None and not is_bitcoin:
            market = await self._long_term_trend(provider_id, self._bitcoin, as_of)
        setup = await self._closed(provider_id, instrument, timeframe, as_of, VOLUME_CANDLES + 1)
        # A day more than the history, so a rate paid at its start is always included.
        rows = await self._market.funding_between(
            provider_id,
            instrument.id,
            as_of - FUNDING_HISTORY - timedelta(days=1),
            as_of + timedelta(milliseconds=1),
        )
        return Conditions(
            long_term_trend=None if own is None else own.agrees(as_of, side),
            bitcoin_trend=None if market is None else market.agrees(as_of, side),
            volume=None if setup is None else VolumeView(setup).confirms(as_of),
            funding=FundingView([(at, rate) for at, rate, _ in rows]).agrees(as_of, side),
            bitcoin_applies=not is_bitcoin,
        )

    async def _long_term_trend(
        self, provider_id: int, instrument: Instrument, as_of: datetime
    ) -> LongTermTrend | None:
        days = await self._closed(provider_id, instrument, Timeframe.D1, as_of, SCORE_DAYS)
        return None if days is None else LongTermTrend(days)

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


def _risk_at_stop(position: Position, stop: tuple[Decimal, str] | None) -> Decimal:
    """What a Binance position loses at its recorded stop, or its whole value if none is known."""
    if stop is None:
        return position.notional
    return abs(position.entry_price - stop[0]) * abs(position.amount)


def _entry_risk(entry: PendingEntry, stop: tuple[Decimal, str] | None) -> Decimal:
    """What a waiting limit entry would lose at its stop once filled, or its whole value."""
    if stop is None:
        return entry.notional
    return abs(entry.price - stop[0]) * entry.quantity


def _against(side: Side, price: Decimal, tick: Decimal) -> Decimal:
    """Round to the tick in the direction that is worse for the trade."""
    rounding = ROUND_CEILING if side.sign > 0 else ROUND_FLOOR
    return (price / tick).to_integral_value(rounding=rounding) * tick
