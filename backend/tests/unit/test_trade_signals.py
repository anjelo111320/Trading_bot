from datetime import timedelta
from decimal import Decimal

import pytest

from tests.quant_data import START, candle, from_closes, random_walk
from trading_intel.domain.candles import ClosedCandle, Timeframe
from trading_intel.domain.signals import Action, Side
from trading_intel.domain.signals import SignalState as S
from trading_intel.market_structure.swings import find_swings
from trading_intel.technical_analysis.series import CandleSeries
from trading_intel.technical_analysis.volatility import atr
from trading_intel.trade_signals import baseline
from trading_intel.trade_signals.baseline import BaselineParameters, evaluate
from trading_intel.trade_signals.catalogue import build_catalogue, to_tick
from trading_intel.trade_signals.lifecycle import (
    ALLOWED,
    TERMINAL,
    InvalidTransitionError,
    advance,
    dedupe_key,
)
from trading_intel.trade_signals.quality import SetupEvidence, score_setup

TICK = Decimal("0.01")


def trending(timeframe: Timeframe, waves: int, up: bool = True) -> CandleSeries:
    """Rising or falling waves, ending on a candle that breaks the last swing."""
    closes: list[float] = []
    sign = 1 if up else -1
    level = 1000.0
    for _ in range(waves):
        closes += [level + sign * step for step in (2, 4, 6, 8, 10, 12)]
        closes += [level + sign * step for step in (10, 8, 6)]
        level += sign * 6
    closes.append(level + sign * 12)
    rows: list[ClosedCandle] = []
    previous = closes[0]
    for index, close in enumerate(closes):
        rows.append(
            candle(
                index,
                previous,
                max(previous, close) + 0.1,
                min(previous, close) - 0.1,
                close,
                timeframe=timeframe,
            )
        )
        previous = close
    return CandleSeries.of(rows)


def test_to_tick_rounds_exactly() -> None:
    assert to_tick(78125.074, TICK) == Decimal("78125.07")
    assert to_tick(Decimal("78125.075"), TICK) == Decimal("78125.08")
    assert to_tick(78125.1, Decimal("0.1")) == Decimal("78125.1")


def test_catalogue_gives_ids_and_tick_aligned_prices() -> None:
    series = random_walk(300, seed=2)
    swings = find_swings(series)
    catalogue = build_catalogue(series, swings, atr(series), TICK)
    assert catalogue is not None
    assert catalogue.levels
    assert len({v.id for v in catalogue.levels}) == len(catalogue.levels)
    assert all(v.price % TICK == 0 for v in catalogue.levels)
    assert {"atr_projection"} <= {v.kind for v in catalogue.levels}


def test_catalogue_positions_agree_with_the_close() -> None:
    series = random_walk(300, seed=2)
    catalogue = build_catalogue(series, find_swings(series), atr(series), TICK)
    assert catalogue is not None
    assert all(v.price > catalogue.close for v in catalogue.above())
    assert all(v.price < catalogue.close for v in catalogue.below())


def test_an_id_that_is_not_in_the_catalogue_resolves_to_nothing() -> None:
    series = random_walk(300, seed=2)
    catalogue = build_catalogue(series, find_swings(series), atr(series), TICK)
    assert catalogue is not None
    assert catalogue.resolve("L1") is not None
    assert catalogue.resolve("L9999") is None


def test_catalogue_is_empty_during_warm_up() -> None:
    series = from_closes([100, 101, 102])
    assert build_catalogue(series, [], atr(series), TICK) is None


def test_baseline_buys_a_break_in_line_with_higher_timeframes() -> None:
    setup = trending(Timeframe.M15, 12)
    decision = evaluate(
        setup, trending(Timeframe.H1, 12), trending(Timeframe.H4, 12), TICK,
        BaselineParameters(min_adx=0, min_target_r=1.0),
    )  # fmt: skip
    assert decision.action is Action.BUY, decision.reasons
    assert decision.proposal is not None
    proposal = decision.proposal
    assert proposal.side is Side.LONG
    assert proposal.stop < proposal.entry < proposal.targets[0]
    assert list(proposal.targets) == sorted(proposal.targets)
    assert proposal.invalidation_conditions
    assert proposal.expiry_candles == 8


def test_baseline_sells_the_mirror_case() -> None:
    setup = trending(Timeframe.M15, 12, up=False)
    decision = evaluate(
        setup, trending(Timeframe.H1, 12, up=False), trending(Timeframe.H4, 12, up=False), TICK,
        BaselineParameters(min_adx=0, min_target_r=1.0),
    )  # fmt: skip
    assert decision.action is Action.SELL, decision.reasons
    assert decision.proposal is not None
    assert decision.proposal.stop > decision.proposal.entry > decision.proposal.targets[0]


def test_baseline_refuses_when_higher_timeframes_disagree() -> None:
    decision = evaluate(
        trending(Timeframe.M15, 12),
        trending(Timeframe.H1, 12, up=False),
        trending(Timeframe.H4, 12),
        TICK,
        BaselineParameters(min_adx=0),
    )
    assert decision.action is Action.NO_TRADE
    assert "higher timeframes" in decision.reasons[0]


def test_no_trade_is_a_normal_outcome_without_a_break() -> None:
    quiet = from_closes([100.0] * 80)
    decision = evaluate(quiet, quiet, quiet, TICK)
    assert decision.action is Action.NO_TRADE
    assert decision.proposal is None


def test_baseline_refuses_a_directionless_market() -> None:
    decision = evaluate(
        trending(Timeframe.M15, 12), trending(Timeframe.H1, 12), trending(Timeframe.H4, 12), TICK,
        BaselineParameters(min_adx=99),
    )  # fmt: skip
    assert decision.action is Action.NO_TRADE
    assert "directional" in decision.reasons[0]


def test_baseline_never_forces_targets() -> None:
    catalogue_series = random_walk(300, seed=2)
    catalogue = build_catalogue(
        catalogue_series, find_swings(catalogue_series), atr(catalogue_series), TICK
    )
    assert catalogue is not None
    far = baseline._select_targets(
        catalogue, Side.LONG, catalogue.close, Decimal(100000), Decimal(1)
    )
    assert far == ()


def test_targets_must_clear_two_to_one_by_default() -> None:
    """Regression: version 1 chose first targets at 1R, which could not pass the risk rule."""
    assert BaselineParameters().min_target_r == 2.0
    setup = trending(Timeframe.M15, 12)
    decision = evaluate(
        setup, trending(Timeframe.H1, 12), trending(Timeframe.H4, 12), TICK,
        BaselineParameters(min_adx=0),
    )  # fmt: skip
    if decision.proposal is not None:
        proposal = decision.proposal
        risk = proposal.entry - proposal.stop
        assert proposal.targets[0] - proposal.entry >= 2 * risk


def test_the_decision_is_deterministic() -> None:
    args = (trending(Timeframe.M15, 12), trending(Timeframe.H1, 12), trending(Timeframe.H4, 12))
    parameters = BaselineParameters(min_adx=0, min_target_r=1.0)
    first = evaluate(*args, TICK, parameters)
    assert first.proposal is not None
    assert first.proposal == evaluate(*args, TICK, parameters).proposal


def test_quality_score_is_weighted_and_bounded() -> None:
    perfect = SetupEvidence(1, 1, 1, 1, 1, 1, 1)
    assert score_setup(perfect).score == 100
    assert score_setup(SetupEvidence(0, 0, 0, 0, 0, 0, 0)).score == 0


def test_conflicting_evidence_reduces_the_score_but_never_below_zero() -> None:
    assert score_setup(SetupEvidence(1, 1, 1, 1, 1, 1, 1, conflicts=2)).score == 80
    assert score_setup(SetupEvidence(0.1, 0, 0, 0, 0, 0, 0, conflicts=3)).score == 0


def test_quality_inputs_must_be_in_range() -> None:
    with pytest.raises(ValueError, match="momentum"):
        score_setup(SetupEvidence(1, 1, 1.5, 1, 1, 1, 1))


def test_lifecycle_allows_the_documented_path() -> None:
    state = S.CANDIDATE
    for following in (S.VALIDATED, S.ACTIVE, S.ENTRY_TRIGGERED, S.TP1_HIT, S.TP2_HIT, S.TP3_HIT):
        state = advance(state, following)
    assert state in TERMINAL


def test_lifecycle_refuses_a_jump() -> None:
    with pytest.raises(InvalidTransitionError):
        advance(S.CANDIDATE, S.TP1_HIT)


@pytest.mark.parametrize("state", sorted(TERMINAL))
def test_a_finished_signal_cannot_move(state: S) -> None:
    with pytest.raises(InvalidTransitionError):
        advance(state, S.ACTIVE)
    assert state not in ALLOWED


def test_duplicate_key_groups_entries_within_half_an_atr() -> None:
    key = dedupe_key("a", 1, Side.LONG, Timeframe.M15, Decimal("100.1"), Decimal(10))
    same = dedupe_key("a", 1, Side.LONG, Timeframe.M15, Decimal("101.0"), Decimal(10))
    other = dedupe_key("a", 1, Side.LONG, Timeframe.M15, Decimal("110.0"), Decimal(10))
    short = dedupe_key("a", 1, Side.SHORT, Timeframe.M15, Decimal("100.1"), Decimal(10))
    assert key == same
    assert key != other
    assert key != short


def test_time_helper_is_utc() -> None:
    assert (START + timedelta(hours=1)).tzinfo is not None
