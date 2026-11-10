"""The money plan's evidence rule, as pre-registered in docs/33 (D045)."""

from datetime import UTC, datetime
from decimal import Decimal as D

from trading_intel.domain.candles import Timeframe
from trading_intel.risk_management.allocation import (
    FULL_SHARE,
    HALF_SHARE,
    QUARTER_SHARE,
    Claim,
    Evidence,
    evidence_share,
    loses_on_coin,
    split,
)
from trading_intel.trade_signals.portfolio import EVIDENCE_SHARES, due, share_of


def evidence(**overrides: object) -> Evidence:
    values: dict[str, object] = {
        "pooled_mean": 0.3,
        "pooled_interval": (0.05, 0.6),
        "new_coins_mean": 0.2,
        "doubled_costs_mean": 0.25,
    }
    values.update(overrides)
    return Evidence(**values)  # type: ignore[arg-type]


def test_a_strategy_that_holds_everywhere_gets_the_full_share() -> None:
    assert evidence_share(evidence()) == FULL_SHARE == D(1)


def test_any_failed_condition_halves_a_positive_strategy() -> None:
    assert evidence_share(evidence(pooled_interval=(-0.01, 0.6))) == HALF_SHARE
    assert evidence_share(evidence(pooled_interval=None)) == HALF_SHARE
    assert evidence_share(evidence(new_coins_mean=0.0)) == HALF_SHARE
    assert evidence_share(evidence(new_coins_mean=None)) == HALF_SHARE
    assert evidence_share(evidence(doubled_costs_mean=-0.1)) == HALF_SHARE


def test_no_edge_or_no_test_gets_a_quarter() -> None:
    assert evidence_share(evidence(pooled_mean=0.0)) == QUARTER_SHARE
    assert evidence_share(evidence(pooled_mean=-0.2, pooled_interval=(0.1, 0.2))) == QUARTER_SHARE
    assert evidence_share(None) == QUARTER_SHARE


def test_only_a_coin_lost_with_95_percent_confidence_is_left_out() -> None:
    assert loses_on_coin((-0.9, -0.01))
    assert not loses_on_coin((-0.9, 0.0))
    assert not loses_on_coin(None)


# A 1,000 account at 1% risk: a full share risks 10, a half 5 and a quarter 2.5.
TREND = Claim("trend:BTC", FULL_SHARE, D(10), D(150))
PATTERN_SOL = Claim("pattern:SOL", HALF_SHARE, D(5), D(300))
PATTERN_XRP = Claim("pattern:XRP", HALF_SHARE, D(5), D(300))
BASELINE = Claim("baseline:ETH", QUARTER_SHARE, D("2.5"), D(200))
ALL = [BASELINE, PATTERN_XRP, TREND, PATTERN_SOL]


def test_signals_that_fit_keep_their_evidence_share() -> None:
    shares = split(ALL, risk_room=D(30), exposure_room=D(1000), slots=10)
    assert shares == {
        "trend:BTC": D(1),
        "pattern:SOL": D("0.5"),
        "pattern:XRP": D("0.5"),
        "baseline:ETH": D("0.25"),
    }


def test_the_best_evidence_is_served_first_and_equals_split_the_rest() -> None:
    shares = split(ALL, risk_room=D(15), exposure_room=D(1000), slots=10)
    assert shares == {"trend:BTC": D(1), "pattern:SOL": D("0.25"), "pattern:XRP": D("0.25")}


def test_size_is_capped_by_the_exposure_room_too() -> None:
    shares = split(ALL, risk_room=D(30), exposure_room=D(450), slots=10)
    assert shares["trend:BTC"] == D(1)
    assert shares["pattern:SOL"] == shares["pattern:XRP"] == D("0.25")
    assert "baseline:ETH" not in shares


def test_free_slots_and_an_empty_budget_are_respected() -> None:
    assert split(ALL, risk_room=D(30), exposure_room=D(1000), slots=2) == {
        "trend:BTC": D(1),
        "pattern:SOL": D("0.5"),
    }
    assert split(ALL, risk_room=D(0), exposure_room=D(1000), slots=10) == {}
    assert split(ALL, risk_room=D(-5), exposure_room=D(1000), slots=10) == {}


def test_shares_never_exceed_the_room_after_rounding() -> None:
    shares = split([PATTERN_SOL, PATTERN_XRP], D(1), D(1000), 10)
    assert shares["pattern:SOL"] == D("0.05")
    assert sum(D(5) * share / HALF_SHARE for share in shares.values()) <= D(1)


def test_the_plan_uses_the_shares_the_study_set() -> None:
    """docs/33, run once on 2026-11-09."""
    study = {"daily_trend": D(1), "pattern_breakout": D("0.5"), "trend_break_baseline": D("0.25")}
    assert dict(EVIDENCE_SHARES) == study
    assert share_of("an untested strategy") == QUARTER_SHARE


def test_each_strategy_joins_the_plan_at_its_own_close() -> None:
    def at(hour: int, minute: int) -> datetime:
        return datetime(2026, 11, 9, hour, minute, 59, 999000, tzinfo=UTC)

    assert due(at(10, 14)) == (Timeframe.M15,)
    assert due(at(10, 59)) == (Timeframe.M15, Timeframe.H1)
    assert due(at(23, 59)) == (Timeframe.M15, Timeframe.H1, Timeframe.D1)
    assert due(at(10, 13)) == ()
