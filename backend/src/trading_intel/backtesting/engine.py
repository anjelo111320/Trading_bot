"""Replay closed candles in time order through the live strategy and risk code.

Strategy code sees only candles closed by the decision time. Fills come from the same
simulator as paper trading, and trades go through the same risk engine.
"""

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from typing import Final, Protocol

from trading_intel.backtesting.metrics import ClosedTrade, Metrics, compute_metrics
from trading_intel.domain.candles import ClosedCandle, Timeframe
from trading_intel.domain.instruments import Instrument, InstrumentRules
from trading_intel.domain.signals import Action
from trading_intel.paper_trading.simulator import (
    SimulatedOrder,
    TradeResult,
    TradeSimulator,
    summarise,
)
from trading_intel.risk_management.engine import assess
from trading_intel.risk_management.models import (
    AccountState,
    FeeRates,
    MarketState,
    RiskProfile,
    RiskRequest,
)
from trading_intel.risk_management.rejections import RejectionCode
from trading_intel.technical_analysis.series import CandleSeries
from trading_intel.trade_signals.baseline import BaselineDecision, BaselineParameters, evaluate

SETUP_LOOKBACK: Final = 400
MIDDLE_LOOKBACK: Final = 200
HIGHER_LOOKBACK: Final = 150
ZERO: Final = Decimal(0)
MIN_SETUP_CANDLES: Final = 60
MIN_MIDDLE_CANDLES: Final = 30
MIN_HIGHER_CANDLES: Final = 20


@dataclass(frozen=True)
class CostModel:
    """Conservative placeholders until recorded spread can replace them."""

    spread_bps: Decimal = Decimal(1)
    taker_fee: Decimal = Decimal("0.0005")
    maker_fee: Decimal = Decimal("0.0002")
    slippage_ticks: int = 2
    slippage_atr_share: Decimal = Decimal("0.05")
    stress: Decimal = Decimal(1)

    def stressed(self, multiple: str) -> CostModel:
        return CostModel(
            self.spread_bps,
            self.taker_fee,
            self.maker_fee,
            self.slippage_ticks,
            self.slippage_atr_share,
            Decimal(multiple),
        )

    def half_spread(self, price: Decimal) -> Decimal:
        return price * self.spread_bps / Decimal(20000) * self.stress

    def slippage(self, tick: Decimal, atr: Decimal) -> Decimal:
        return max(self.slippage_ticks * tick, self.slippage_atr_share * atr) * self.stress

    def fees(self) -> tuple[Decimal, Decimal]:
        return self.taker_fee * self.stress, self.maker_fee * self.stress


@dataclass(frozen=True)
class FundingEvent:
    at: datetime
    rate: Decimal
    mark: Decimal


class AsOfCandles:
    """Time-gated access. Candles closing after the moment simply cannot be reached."""

    def __init__(self, candles: Sequence[ClosedCandle]) -> None:
        self._candles = list(candles)
        self._close_times = [c.close_time for c in self._candles]

    def closed_by(self, moment: datetime, limit: int) -> list[ClosedCandle]:
        end = bisect_right(self._close_times, moment)
        return self._candles[max(end - limit, 0) : end]


class Strategy(Protocol):
    """Decides at the close of each setup candle, from what was known at that moment."""

    @property
    def timeframe(self) -> Timeframe: ...

    def decide(self, moment: datetime) -> BaselineDecision | None: ...


class WindowedBaseline:
    """The rule baseline, fed windows of candles that had closed by each decision."""

    timeframe: Final = Timeframe.M15

    def __init__(
        self,
        setup: Sequence[ClosedCandle],
        middle: Sequence[ClosedCandle],
        higher: Sequence[ClosedCandle],
        tick: Decimal,
        parameters: BaselineParameters,
    ) -> None:
        self._setup = AsOfCandles(setup)
        self._middle = AsOfCandles(middle)
        self._higher = AsOfCandles(higher)
        self._tick = tick
        self._parameters = parameters

    def decide(self, moment: datetime) -> BaselineDecision | None:
        setup = self._setup.closed_by(moment, SETUP_LOOKBACK)
        middle = self._middle.closed_by(moment, MIDDLE_LOOKBACK)
        higher = self._higher.closed_by(moment, HIGHER_LOOKBACK)
        if (
            len(setup) < MIN_SETUP_CANDLES
            or len(middle) < MIN_MIDDLE_CANDLES
            or len(higher) < MIN_HIGHER_CANDLES
        ):
            return None
        return evaluate(
            CandleSeries.of(setup),
            CandleSeries.of(middle),
            CandleSeries.of(higher),
            self._tick,
            self._parameters,
        )


@dataclass(frozen=True)
class BacktestTrade:
    signal_time: datetime
    order: SimulatedOrder
    result: TradeResult
    planned_risk: Decimal
    decision: BaselineDecision | None = None


@dataclass
class BacktestResult:
    trades: list[BacktestTrade] = field(default_factory=list)
    equity: list[tuple[datetime, Decimal]] = field(default_factory=list)
    rejections: dict[RejectionCode, int] = field(default_factory=dict)
    decisions: int = 0
    signals: int = 0
    metrics: Metrics | None = None


def _ceil_to_tick(value: Decimal, tick: Decimal) -> Decimal:
    return (value / tick).to_integral_value(rounding=ROUND_CEILING) * tick


class BacktestEngine:
    def __init__(
        self,
        instrument: Instrument,
        rules: InstrumentRules,
        minutes: Sequence[ClosedCandle],
        setup: Sequence[ClosedCandle],
        middle: Sequence[ClosedCandle],
        higher: Sequence[ClosedCandle],
        funding: Sequence[FundingEvent] = (),
        *,
        parameters: BaselineParameters | None = None,
        costs: CostModel | None = None,
        profile: RiskProfile | None = None,
        starting_equity: Decimal = Decimal(10000),
        strategy: Strategy | None = None,
        skip_signals_in_trade: bool = False,
    ) -> None:
        """`minutes` are the fill candles, normally 1M. `strategy` defaults to the baseline.

        With `skip_signals_in_trade`, no decision is made while a position is open. Otherwise
        a signal waits for the open trade to finish and may fill late, until it expires.
        """
        self._instrument = instrument
        self._rules = rules
        self._minutes = list(minutes)
        self._setup_candles = list(setup)
        self._funding = list(funding)
        self._strategy: Strategy = strategy or WindowedBaseline(
            setup, middle, higher, rules.tick_size, parameters or BaselineParameters()
        )
        self._costs = costs or CostModel()
        self._profile = profile or RiskProfile()
        self._equity = starting_equity
        self._starting_equity = starting_equity
        self._skip_in_trade = skip_signals_in_trade
        self._free_at: datetime | None = None
        self._pending: BaselineDecision | None = None

    def run(self, start: datetime, end: datetime) -> BacktestResult:
        result = BacktestResult(equity=[(start, self._equity)])
        cursor = 0
        for candle in self._setup_candles:
            if candle.close_time < start or candle.close_time >= end:
                continue
            if self._skip_in_trade and self._free_at and candle.close_time < self._free_at:
                continue
            result.decisions += 1
            order = self._decide(candle, result)
            if order is None:
                continue
            cursor = self._simulate(order, candle.close_time, end, cursor, result)
        days = max((end - start).days, 1)
        closed = [self._closed(t) for t in result.trades if t.result.entered]
        result.metrics = compute_metrics(
            [t for t in closed if t is not None],
            [value for _, value in result.equity],
            self._starting_equity,
            days,
        )
        return result

    def _closed(self, trade: BacktestTrade) -> ClosedTrade | None:
        outcome = trade.result
        if outcome.entry_time is None or outcome.exit_time is None:
            return None
        return ClosedTrade(
            entry_time=outcome.entry_time,
            exit_time=outcome.exit_time,
            net_pnl=outcome.net_pnl,
            r_multiple=outcome.net_pnl / trade.planned_risk if trade.planned_risk else ZERO,
            costs=outcome.fees - outcome.funding + outcome.spread_cost + outcome.slippage_cost,
            gross_pnl=outcome.gross_pnl,
        )

    def _fill_scale(self) -> int:
        """Setup candles per fill candle, which scales setup ATR down to the fill timeframe."""
        if not self._minutes:
            return 1
        fill = self._minutes[0].timeframe.delta
        return max(int(self._strategy.timeframe.delta / fill), 1)

    def _decide(self, candle: ClosedCandle, result: BacktestResult) -> SimulatedOrder | None:
        moment = candle.close_time
        decision = self._strategy.decide(moment)
        if decision is None:
            return None
        if decision.action not in (Action.BUY, Action.SELL) or decision.proposal is None:
            return None
        result.signals += 1
        self._pending = decision
        proposal = decision.proposal
        assert decision.setup_atr is not None
        tick = self._rules.tick_size
        half = _ceil_to_tick(self._costs.half_spread(candle.close), tick)
        slippage = self._costs.slippage(tick, decision.setup_atr / self._fill_scale())
        taker, maker = self._costs.fees()
        request = RiskRequest(
            proposal=proposal,
            account=AccountState(
                equity=self._equity,
                day_start_equity=self._equity,
                open_positions=0,
                gross_exposure=ZERO,
            ),
            market=MarketState(
                bid=candle.close - half,
                ask=candle.close + half,
                entry_slippage=slippage,
                stop_slippage=slippage,
                setup_atr=decision.setup_atr,
                data_age_seconds=0,
            ),
            instrument=self._instrument,
            rules=self._rules,
            fees=FeeRates(entry=taker, exit=taker),
            profile=self._profile,
        )
        assessment = assess(request)
        if not assessment.approved or assessment.sizing is None:
            for code in assessment.codes:
                result.rejections[code] = result.rejections.get(code, 0) + 1
            return None
        sizing = assessment.sizing
        expires = moment + self._strategy.timeframe.delta * (proposal.expiry_candles or 1)
        return SimulatedOrder(
            side=proposal.side,
            entry_type=proposal.entry_type,
            entry=proposal.entry,
            stop=proposal.stop,
            targets=proposal.targets,
            allocation=sizing.allocation,
            quantity=sizing.quantity,
            tick=tick,
            lot_step=self._rules.lot_step,
            taker_fee=taker,
            maker_fee=maker,
            half_spread=half,
            entry_slippage=slippage,
            stop_slippage=slippage,
            placed_at=moment + timedelta(milliseconds=1),
            expires_at=expires,
        )

    def _simulate(
        self,
        order: SimulatedOrder,
        signal_time: datetime,
        end: datetime,
        cursor: int,
        result: BacktestResult,
    ) -> int:
        """Run one trade to its end. A new signal waits until this one has finished."""
        simulator = TradeSimulator(order)
        funding = [f for f in self._funding if f.at >= signal_time]
        index = cursor
        while index < len(self._minutes):
            candle = self._minutes[index]
            index += 1
            if candle.open_time < order.placed_at:
                continue
            if candle.open_time >= end:
                break
            while funding and funding[0].at < candle.close_time:
                event = funding.pop(0)
                simulator.on_funding(event.at, event.rate, event.mark)
            simulator.on_candle(candle)
            if simulator.is_finished:
                self._free_at = candle.close_time
                break
        outcome = summarise(order.side, simulator.fills)
        planned = order.quantity * abs(order.entry - order.stop)
        if outcome.entered and simulator.is_finished:
            self._equity += outcome.net_pnl
            if outcome.exit_time is not None:
                result.equity.append((outcome.exit_time, self._equity))
            result.trades.append(BacktestTrade(signal_time, order, outcome, planned, self._pending))
        elif outcome.entered:
            self._free_at = end  # Still open when the window ended.
        return index
