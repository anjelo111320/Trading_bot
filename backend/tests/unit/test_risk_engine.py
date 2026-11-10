"""The worked examples in docs/08-RISK-MANAGEMENT.md, every rejection code and boundaries."""

from decimal import Decimal as D
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from trading_intel.domain.instruments import Instrument, InstrumentRules, InstrumentType
from trading_intel.domain.signals import EntryType, Side
from trading_intel.risk_management.calculators.linear import floor_to_step
from trading_intel.risk_management.engine import assess, assess_raw
from trading_intel.risk_management.models import (
    AccountState,
    FeeRates,
    MarketState,
    RiskAssessment,
    RiskProfile,
    RiskRequest,
    TradeProposal,
)
from trading_intel.risk_management.rejections import RejectionCode as Code


def instrument(kind: InstrumentType = InstrumentType.SPOT) -> Instrument:
    return Instrument(
        id=1,
        symbol="TESTUSDT",
        instrument_type=kind,
        base_asset="TEST",
        quote_asset="USDT",
        settle_asset="USDT",
    )


def rules(**overrides: Any) -> InstrumentRules:
    values: dict[str, Any] = {
        "status": "TRADING",
        "tick_size": D("0.01"),
        "lot_step": D("0.01"),
        "min_qty": D("0.01"),
        "max_qty": D(100000),
        "min_notional": D(5),
        "maintenance_margin_fraction": D("0.025"),
        "raw": {},
    }
    return InstrumentRules(**{**values, **overrides})


def proposal(**overrides: Any) -> TradeProposal:
    values: dict[str, Any] = {
        "side": Side.LONG,
        "entry_type": EntryType.MARKET,
        "entry": D("100.00"),
        "stop": D("98.00"),
        "targets": (D("104.00"), D("106.00"), D("108.00")),
        "invalidation_conditions": ("close below 98",),
    }
    return TradeProposal(**{**values, **overrides})


def market(**overrides: Any) -> MarketState:
    values: dict[str, Any] = {
        "bid": D("99.99"),
        "ask": D("100.01"),
        "entry_slippage": D("0.02"),
        "stop_slippage": D("0.05"),
        "data_age_seconds": 1,
    }
    return MarketState(**{**values, **overrides})


def request(**overrides: Any) -> RiskRequest:
    values: dict[str, Any] = {
        "proposal": proposal(),
        "account": AccountState(
            equity=D(10000), day_start_equity=D(10000), open_positions=0, gross_exposure=D(0)
        ),
        "market": market(),
        "instrument": instrument(),
        "rules": rules(),
        "fees": FeeRates(entry=D("0.001"), exit=D("0.001")),
        "profile": RiskProfile(),
    }
    return RiskRequest(**{**values, **overrides})


def example_b(leverage: str = "3") -> RiskRequest:
    return request(
        proposal=proposal(
            side=Side.SHORT,
            entry=D("100.00"),
            stop=D("102.00"),
            targets=(D("96.00"), D("94.00")),
            leverage=D(leverage),
        ),
        market=market(funding_rate=D("0.0001"), funding_intervals=2),
        instrument=instrument(InstrumentType.LINEAR_PERPETUAL),
        fees=FeeRates(entry=D("0.0005"), exit=D("0.0005")),
        profile=RiskProfile(target_allocation=(D("0.5"), D("0.5"))),
    )


def codes(result: RiskAssessment) -> set[Code]:
    return set(result.codes)


def test_a_target_at_or_below_zero_is_refused() -> None:
    """Regression: a short's profit cap below zero reached the database on 2026-11-07."""
    short = proposal(
        side=Side.SHORT,
        stop=D("102.00"),
        targets=(D("90.00"), D("-0.06")),
        invalidation_conditions=("close above 102",),
    )
    assert Code.TARGET_WRONG_SIDE in codes(assess(request(proposal=short)))


def test_example_a_is_approved_with_the_documented_numbers() -> None:
    result = assess(request())
    sizing = result.sizing
    assert result.approved
    assert sizing is not None
    assert sizing.risk_budget == D("100.00")
    assert sizing.entry_fill == D("100.03")
    assert sizing.stop_fill == D("97.94")
    assert sizing.entry_fee == D("0.10003")
    assert sizing.stop_fee == D("0.09794")
    assert sizing.risk_per_unit == D("2.28797")
    assert sizing.quantity == D("43.70")
    assert round(sizing.max_account_risk, 2) == D("99.98")
    assert round(sizing.notional, 2) == D("4371.31")
    assert [round(r, 3) for r in sizing.target_reward_risk] == [D("1.646"), D("2.519"), D("3.393")]
    assert round(sizing.weighted_reward_risk, 3) == D("2.257")


def test_example_b_is_approved_and_leverage_does_not_change_risk() -> None:
    result = assess(example_b("3"))
    sizing = result.sizing
    assert result.approved
    assert sizing is not None
    assert sizing.entry_fill == D("99.97")
    assert sizing.stop_fill == D("102.06")
    assert sizing.funding == D("0.020412")
    assert sizing.risk_per_unit == D("2.211427")
    assert sizing.quantity == D("45.21")
    assert round(sizing.max_account_risk, 2) == D("99.98")
    assert round(sizing.notional, 2) == D("4519.64")
    assert [round(r, 3) for r in sizing.target_reward_risk] == [D("1.742"), D("2.647")]
    assert round(sizing.weighted_reward_risk, 3) == D("2.194")


@pytest.mark.parametrize(
    ("leverage", "margin", "liquidation"),
    [("1", "4519.64", "197.44"), ("3", "1506.55", "130.79"), ("10", "451.96", "107.47")],
)
def test_example_b_leverage_table(leverage: str, margin: str, liquidation: str) -> None:
    sizing = assess(example_b(leverage)).sizing
    assert sizing is not None
    assert round(sizing.margin, 2) == D(margin)
    assert sizing.liquidation_price is not None
    assert round(sizing.liquidation_price, 2) == D(liquidation)
    assert round(sizing.max_account_risk, 2) == D("99.98")
    assert sizing.quantity == D("45.21")


def test_example_b_ten_times_leverage_is_refused() -> None:
    assert codes(assess(example_b("10"))) == {Code.LEVERAGE_EXCEEDED}


def test_example_c_passes_gross_but_fails_after_costs() -> None:
    result = assess(request(proposal=proposal(targets=(D("104.00"),))))
    assert not result.approved
    assert codes(result) == {Code.RR_BELOW_MIN}
    assert result.sizing is not None
    assert round(result.sizing.weighted_reward_risk, 3) == D("1.646")


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"rules": None}, Code.INSTRUMENT_RULES_MISSING),
        ({"fees": None}, Code.FEE_SCHEDULE_MISSING),
        ({"rules": rules(status="BREAK")}, Code.MARKET_NOT_TRADING),
        ({"market": market(data_age_seconds=31)}, Code.DATA_STALE),
        ({"market": market(has_open_gaps=True)}, Code.DATA_INCOMPLETE),
        ({"market": market(bid=D("99.90"), ask=D("100.10"))}, Code.SPREAD_TOO_WIDE),
        ({"proposal": proposal(entry=D("105.00"))}, Code.INVALID_ENTRY),
        ({"proposal": proposal(stop=D("101.00"))}, Code.STOP_WRONG_SIDE),
        ({"proposal": proposal(targets=(D("99.00"),))}, Code.TARGET_WRONG_SIDE),
        (
            {"proposal": proposal(targets=(D("106.00"), D("104.00")))},
            Code.TARGET_ORDER_INVALID,
        ),
        ({"proposal": proposal(stop=D("98.005"))}, Code.NOT_TICK_ALIGNED),
        ({"proposal": proposal(targets=())}, Code.NO_TARGET),
        ({"proposal": proposal(targets=(D("104.00"),))}, Code.RR_BELOW_MIN),
        ({"proposal": proposal(targets=(D("100.10"),))}, Code.TP1_NOT_PROFITABLE),
        ({"rules": rules(min_qty=D(50))}, Code.QTY_BELOW_MIN),
        ({"rules": rules(max_qty=D(40))}, Code.QTY_ABOVE_MAX),
        ({"rules": rules(min_notional=D(5000))}, Code.NOTIONAL_BELOW_MIN),
        (
            {
                "account": AccountState(
                    equity=D(9700),
                    day_start_equity=D(10000),
                    open_positions=0,
                    gross_exposure=D(0),
                )
            },
            Code.DAILY_LOSS_REACHED,
        ),
        (
            {
                "account": AccountState(
                    equity=D(10000),
                    day_start_equity=D(10000),
                    open_positions=3,
                    gross_exposure=D(0),
                )
            },
            Code.MAX_OPEN_POSITIONS,
        ),
        (
            {
                "account": AccountState(
                    equity=D(10000),
                    day_start_equity=D(10000),
                    open_positions=0,
                    gross_exposure=D(9000),
                )
            },
            Code.EXPOSURE_EXCEEDED,
        ),
        ({"proposal": proposal(leverage=D(2))}, Code.LEVERAGE_EXCEEDED),
        ({"duplicate_active": True}, Code.DUPLICATE_ACTIVE_SIGNAL),
        ({"proposal": proposal(expiry_candles=None)}, Code.EXPIRY_INVALID),
        ({"proposal": proposal(expiry_candles=25)}, Code.EXPIRY_INVALID),
        ({"proposal": proposal(invalidation_conditions=())}, Code.INVALIDATION_MISSING),
    ],
)
def test_each_rejection_code(change: dict[str, Any], expected: Code) -> None:
    result = assess(request(**change))
    assert not result.approved
    assert expected in result.codes


PLAN = RiskProfile(
    max_open_positions=10, max_open_risk_fraction=D("0.03"), daily_profit_stop_fraction=D("0.03")
)


def account(**overrides: Any) -> AccountState:
    values: dict[str, Any] = {
        "equity": D(10000),
        "day_start_equity": D(10000),
        "open_positions": 0,
        "gross_exposure": D(0),
    }
    return AccountState(**{**values, **overrides})


def test_a_risk_share_lowers_the_budget_and_nothing_else() -> None:
    full = assess(request()).sizing
    half = assess(request(proposal=proposal(risk_share=D("0.5")))).sizing
    assert full is not None and half is not None
    assert half.risk_budget == D("50.00")
    assert half.quantity == D("21.85")
    assert half.target_reward_risk == full.target_reward_risk


@pytest.mark.parametrize("share", [D(0), D("-0.5"), D("1.01")])
def test_a_risk_share_can_never_raise_risk_or_be_empty(share: D) -> None:
    with pytest.raises(ValidationError):
        proposal(risk_share=share)
    payload = request().model_dump(mode="python")
    payload["proposal"]["risk_share"] = share
    assert assess_raw(payload).codes == (Code.SCHEMA_INVALID,)


def test_the_money_plan_stops_new_trades_at_three_percent_up() -> None:
    up = account(equity=D(10300))
    result = assess(request(account=up, profile=PLAN))
    assert result.codes == (Code.DAILY_PROFIT_REACHED,)
    nearly = account(equity=D("10299.99"))
    assert assess(request(account=nearly, profile=PLAN)).approved


def test_open_risk_shrinks_a_trade_to_the_room_left_then_refuses() -> None:
    sizing = assess(request(account=account(open_risk=D(260)), profile=PLAN)).sizing
    assert sizing is not None
    assert sizing.risk_budget == D(40)
    assert sizing.max_account_risk <= D(40)
    full = assess(request(account=account(open_risk=D(300)), profile=PLAN))
    assert Code.OPEN_RISK_FULL in full.codes


def test_accounts_without_the_plan_ignore_open_risk_and_profit() -> None:
    busy = account(equity=D(10500), open_risk=D(5000))
    assert assess(request(account=busy)).approved


def test_the_plan_limits_stay_inside_their_ceilings() -> None:
    with pytest.raises(ValidationError):
        RiskProfile(max_open_risk_fraction=D("0.005"))
    with pytest.raises(ValidationError):
        RiskProfile(max_open_risk_fraction=D("0.2"))
    with pytest.raises(ValidationError):
        RiskProfile(daily_profit_stop_fraction=D(0))


def test_unsupported_instrument_is_refused() -> None:
    other = instrument().model_copy(update={"instrument_type": "forex"})
    result = assess(request().model_copy(update={"instrument": other}))
    assert result.codes == (Code.INSTRUMENT_NOT_SUPPORTED,)


def test_direction_and_levels_disagreeing_is_named() -> None:
    wrong = proposal(side=Side.LONG, stop=D("102.00"), targets=(D("96.00"),))
    result = assess(request(proposal=wrong))
    assert {Code.INVALID_DIRECTION, Code.STOP_WRONG_SIDE, Code.TARGET_WRONG_SIDE} <= codes(result)


def test_liquidation_before_the_stop_is_refused() -> None:
    far_stop = example_b("3").proposal.model_copy(
        update={
            "stop": D("131.00"),
            "targets": (D("10.00"),),
        }
    )
    result = assess(example_b("3").model_copy(update={"proposal": far_stop}))
    assert Code.LIQUIDATION_INSIDE_STOP in result.codes


def test_liquidation_needs_one_atr_of_room() -> None:
    base = example_b("3")
    near = base.market.model_copy(update={"setup_atr": D(40)})
    result = assess(base.model_copy(update={"market": near}))
    assert Code.LIQUIDATION_INSIDE_STOP in result.codes


def test_all_failures_are_returned_together() -> None:
    result = assess(
        request(
            proposal=proposal(stop=D("101.00"), invalidation_conditions=()),
            market=market(data_age_seconds=99),
            duplicate_active=True,
        )
    )
    assert {
        Code.STOP_WRONG_SIDE,
        Code.DATA_STALE,
        Code.DUPLICATE_ACTIVE_SIGNAL,
        Code.INVALIDATION_MISSING,
    } <= codes(result)


def test_an_invalid_stop_is_rejected_never_moved() -> None:
    bad = proposal(stop=D("101.00"))
    assess(request(proposal=bad))
    assert bad.stop == D("101.00")


def valid_payload() -> dict[str, Any]:
    return request().model_dump()


def test_float_input_is_refused() -> None:
    payload = valid_payload()
    payload["proposal"]["entry"] = 100.0
    assert assess_raw(payload).codes == (Code.SCHEMA_INVALID,)


def test_malformed_input_is_refused() -> None:
    assert assess_raw({"proposal": "buy everything"}).codes == (Code.SCHEMA_INVALID,)


def test_an_unknown_field_such_as_an_override_is_refused() -> None:
    payload = valid_payload()
    payload["override_risk_checks"] = True
    assert assess_raw(payload).codes == (Code.SCHEMA_INVALID,)


def test_a_valid_payload_passes_through_the_raw_entry() -> None:
    assert assess_raw(valid_payload()).approved


def test_reward_risk_exactly_at_the_minimum_passes() -> None:
    sizing = assess(request(proposal=proposal(targets=(D("104.00"),)))).sizing
    assert sizing is not None
    exact = RiskProfile(min_reward_risk=max(sizing.weighted_reward_risk, D(1)))
    result = assess(request(proposal=proposal(targets=(D("104.00"),)), profile=exact))
    assert Code.RR_BELOW_MIN not in result.codes


def test_countertrend_needs_extra_reward() -> None:
    plain = assess(request())
    counter = assess(request(proposal=proposal(is_countertrend=True)))
    assert plain.approved
    assert Code.RR_BELOW_MIN in counter.codes


def test_budget_shrinks_to_what_remains_of_the_daily_limit() -> None:
    account = AccountState(
        equity=D(9750), day_start_equity=D(10000), open_positions=0, gross_exposure=D(0)
    )
    sizing = assess(request(account=account)).sizing
    assert sizing is not None
    assert sizing.risk_budget == D(50)


def test_notional_exactly_at_the_minimum_passes() -> None:
    sizing = assess(request()).sizing
    assert sizing is not None
    exact = assess(request(rules=rules(min_notional=sizing.notional)))
    assert Code.NOTIONAL_BELOW_MIN not in exact.codes


def test_daily_limit_exactly_reached_blocks_entries() -> None:
    account = AccountState(
        equity=D(9700), day_start_equity=D(10000), open_positions=0, gross_exposure=D(0)
    )
    assert Code.DAILY_LOSS_REACHED in assess(request(account=account)).codes


def test_market_order_near_the_book_is_accepted_and_far_is_refused() -> None:
    assert assess(request()).approved
    assert Code.INVALID_ENTRY in assess(request(proposal=proposal(entry=D("100.20")))).codes


def test_limit_entry_pays_no_entry_spread_or_slippage() -> None:
    limit = proposal(entry_type=EntryType.LIMIT, entry=D("99.50"), targets=(D("108.00"),))
    sizing = assess(request(proposal=limit)).sizing
    assert sizing is not None
    assert sizing.entry_fill == D("99.50")


@pytest.mark.parametrize(
    ("entry_type", "side", "entry", "possible"),
    [
        (EntryType.LIMIT, Side.LONG, "99.00", True),
        (EntryType.LIMIT, Side.LONG, "100.02", False),
        (EntryType.LIMIT, Side.SHORT, "101.00", True),
        (EntryType.LIMIT, Side.SHORT, "99.98", False),
        (EntryType.STOP, Side.LONG, "101.00", True),
        (EntryType.STOP, Side.LONG, "100.00", False),
        (EntryType.STOP, Side.SHORT, "99.00", True),
        (EntryType.STOP, Side.SHORT, "100.00", False),
    ],
)
def test_impossible_entries_for_the_order_type(
    entry_type: EntryType, side: Side, entry: str, possible: bool
) -> None:
    price = D(entry)
    stop = price - 2 if side is Side.LONG else price + 2
    targets = (price + 8,) if side is Side.LONG else (price - 8,)
    result = assess(
        request(
            proposal=proposal(
                side=side, entry_type=entry_type, entry=price, stop=stop, targets=targets
            )
        )
    )
    assert (Code.INVALID_ENTRY not in result.codes) is possible


def test_fewer_targets_rescale_their_allocation() -> None:
    sizing = assess(request(proposal=proposal(targets=(D("106.00"), D("108.00"))))).sizing
    assert sizing is not None
    assert sizing.allocation == (D("0.625"), D("0.375"))


@pytest.mark.parametrize(
    "bad",
    [
        {"max_risk_fraction": D("0.03")},
        {"min_reward_risk": D("0.5")},
        {"max_daily_loss_fraction": D("0.06")},
        {"max_leverage": D(6)},
        {"target_allocation": (D("0.5"), D("0.4"))},
    ],
)
def test_a_profile_cannot_exceed_the_hard_ceilings(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        RiskProfile(**bad)


def test_floor_to_step() -> None:
    assert floor_to_step(D("43.7069"), D("0.01")) == D("43.70")
    assert floor_to_step(D("0.009"), D("0.01")) == D(0)


money = st.decimals(min_value=D("0.5"), max_value=D(50), places=2)


@settings(max_examples=150)
@given(
    distance=money,
    equity=st.decimals(min_value=D(1000), max_value=D(1000000), places=2),
    side=st.sampled_from(list(Side)),
)
def test_actual_risk_never_exceeds_the_budget(distance: D, equity: D, side: Side) -> None:
    entry = D("100.00")
    stop = entry - side.sign * distance
    target = entry + side.sign * distance * 4
    if target <= 0 or stop <= 0:
        return
    result = assess(
        request(
            proposal=proposal(side=side, entry=entry, stop=stop, targets=(target,)),
            account=AccountState(
                equity=equity, day_start_equity=equity, open_positions=0, gross_exposure=D(0)
            ),
        )
    )
    sizing = result.sizing
    assert sizing is not None
    assert sizing.max_account_risk <= sizing.risk_budget
    assert sizing.quantity % D("0.01") == 0
    assert sizing.quantity >= 0


@settings(max_examples=60)
@given(leverage=st.sampled_from(["1", "1.5", "2", "3", "4", "5"]))
def test_leverage_never_changes_quantity_or_risk(leverage: str) -> None:
    base = assess(example_b("1")).sizing
    other = assess(example_b(leverage)).sizing
    assert base is not None and other is not None
    assert base.quantity == other.quantity
    assert base.max_account_risk == other.max_account_risk


def test_long_and_short_are_symmetrical() -> None:
    long = assess(request(market=market(bid=D("100.00"), ask=D("100.00")))).sizing
    short = assess(
        request(
            proposal=proposal(
                side=Side.SHORT,
                stop=D("102.00"),
                targets=(D("96.00"), D("94.00"), D("92.00")),
            ),
            market=market(bid=D("100.00"), ask=D("100.00")),
        )
    ).sizing
    assert long is not None and short is not None
    assert long.entry_fill - 100 == 100 - short.entry_fill
    assert short.stop_fill - 102 == 98 - long.stop_fill


def test_every_rejection_code_is_covered_here() -> None:
    source = Path(__file__).read_text()
    missing = [code.name for code in Code if f"Code.{code.name}" not in source]
    assert missing == []


def test_independent_exact_arithmetic_agrees_with_example_a() -> None:
    """A separate calculation in exact fractions, sharing no code with the engine."""
    half, entry_slip, stop_slip, fee = (
        Fraction(1, 100),
        Fraction(2, 100),
        Fraction(5, 100),
        Fraction(1, 1000),
    )
    entry = 100 + half + entry_slip
    stop = 98 - half - stop_slip
    unit = (entry - stop) + fee * entry + fee * stop
    quantity = Fraction(int(100 / unit * 100), 100)

    def win(target: Fraction) -> Fraction:
        return target - entry - fee * entry - fee * target

    weighted = sum(
        share * win(Fraction(t)) / unit
        for share, t in (
            (Fraction(1, 2), 104),
            (Fraction(3, 10), 106),
            (Fraction(1, 5), 108),
        )
    )
    sizing = assess(request()).sizing
    assert sizing is not None
    assert D(unit.numerator) / D(unit.denominator) == sizing.risk_per_unit
    assert D(quantity.numerator) / D(quantity.denominator) == sizing.quantity
    assert round(float(weighted), 9) == round(float(sizing.weighted_reward_risk), 9)


def test_an_exchange_account_refuses_margin_it_does_not_have() -> None:
    """D048: Binance's available margin, when given, must cover the trade at its leverage."""
    funded = account(available_margin=D(3000))
    at_one = assess(example_b("1").model_copy(update={"account": funded}))
    assert codes(at_one) == {Code.MARGIN_INSUFFICIENT}
    at_two = assess(example_b("2").model_copy(update={"account": funded}))
    assert at_two.approved
    assert at_one.sizing is not None and at_two.sizing is not None
    assert at_two.sizing.max_account_risk == at_one.sizing.max_account_risk
    assert assess(example_b("1")).approved  # Paper accounts give no margin and are unchanged.
