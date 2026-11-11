"""The AI exit manager in shadow mode (D051): checks, facts, the Claude call and scoring replays.

No request leaves this computer: the real SDK talks to a local fake transport.
"""

import json
from datetime import datetime, timedelta
from decimal import Decimal as D
from typing import Any
from uuid import uuid4

import anthropic
import httpx2
import pytest
from pydantic import ValidationError

from tests.quant_data import START, candle
from trading_intel.ai_analyst.exit_checks import (
    REJECTED,
    STALL,
    VOLATILITY,
    PriorReview,
    TradeAtClose,
    fired_checks,
    usual_range,
)
from trading_intel.ai_analyst.exit_review import (
    MODEL,
    PROMPT_BODY,
    ClaudeExitReviewer,
    ExitAdvice,
    TradeFacts,
    render_facts,
)
from trading_intel.ai_analyst.exit_service import r_of, replay_trade
from trading_intel.database.repositories.paper import OpenTrade
from trading_intel.domain.candles import ClosedCandle, Timeframe
from trading_intel.domain.signals import EntryType, Side, SignalState


def m15(index: int, open_: str, high: str, low: str, close: str) -> ClosedCandle:
    return candle(index, float(open_), float(high), float(low), float(close), 1000.0, Timeframe.M15)


def at_close(**changes: Any) -> TradeAtClose:
    values: dict[str, Any] = {
        "side": Side.LONG,
        "entry": D(100),
        "risk": D(2),
        "targets": (D(104), D(106)),
        "targets_hit": 0,
        "tick": D("0.01"),
        "best": D("102.40"),
        "best_at": START,
        "close_time": START + timedelta(hours=2),
    }
    return TradeAtClose(**{**values, **changes})


QUIET = m15(8, "102", "102.2", "101.9", "102.1")


def test_a_stall_needs_plus_one_r_and_two_hours_and_fires_once_per_best() -> None:
    assert fired_checks(at_close(), QUIET, None, []) == (STALL,)
    assert fired_checks(at_close(best=D("101.90")), QUIET, None, []) == ()
    late = at_close(close_time=START + timedelta(hours=1, minutes=45))
    assert fired_checks(late, QUIET, None, []) == ()
    asked = PriorReview((STALL,), 0, START, START + timedelta(hours=2))
    assert fired_checks(at_close(), QUIET, None, [asked]) == (), "already asked about this best"
    newer = at_close(best_at=START + timedelta(minutes=15), close_time=START + timedelta(hours=3))
    assert fired_checks(newer, QUIET, None, [asked]) == (STALL,), "a new best re-arms it"


def test_a_rejection_near_the_next_target_fires_once_per_target() -> None:
    trade = at_close(best=D("101.50"))
    rejected = m15(8, "102.5", "103.6", "102.4", "102.5")  # 0.4 short of 104, 1.1 back.
    assert fired_checks(trade, rejected, None, []) == (REJECTED,)
    through = m15(8, "102.5", "104.01", "102.4", "102.5")
    assert fired_checks(trade, through, None, []) == ()
    held = m15(8, "102.5", "103.6", "102.4", "103.3")
    assert fired_checks(trade, held, None, []) == (), "it did not close back far enough"
    asked = PriorReview((REJECTED,), 0, None, START)
    assert fired_checks(trade, rejected, None, [asked]) == ()
    assert fired_checks(at_close(best=D("101.50"), targets_hit=2), rejected, None, []) == ()
    short = at_close(side=Side.SHORT, entry=D(100), best=D("98.50"), targets=(D(96),))
    assert fired_checks(short, m15(8, "97.5", "97.6", "96.4", "97.5"), None, []) == (REJECTED,)


def test_a_volatility_jump_fires_at_most_every_two_hours() -> None:
    trade = at_close(best=D(101))
    wide = m15(8, "101", "102", "100", "101.5")  # A range of 2.
    assert fired_checks(trade, wide, D("0.6"), []) == (VOLATILITY,)
    assert fired_checks(trade, wide, D("0.7"), []) == ()
    recent = PriorReview((VOLATILITY,), 0, None, START + timedelta(hours=1))
    assert fired_checks(trade, wide, D("0.6"), [recent]) == ()
    assert fired_checks(trade, wide, None, []) == ()


def test_the_usual_range_is_the_median_of_the_96_candles_before_the_last() -> None:
    rows = [m15(i, "100", "101", "100", "100.5") for i in range(96)]
    rows.append(m15(96, "100", "110", "90", "100"))
    assert usual_range(rows) == D(1)
    assert usual_range(rows[:96]) is None


def facts(**changes: Any) -> TradeFacts:
    values: dict[str, Any] = {
        "symbol": "SOLUSDT",
        "strategy": "pattern_breakout",
        "account": "Portfolio",
        "side": Side.LONG,
        "entry": D("84.10"),
        "risk": D("2.00"),
        "stop": D("82.10"),
        "targets": (D("88.10"), D("90.10")),
        "targets_hit": 1,
        "price": D("86.50"),
        "best": D("88.30"),
        "worst": D("83.90"),
        "best_age": timedelta(hours=2, minutes=30),
        "open_for": timedelta(days=1, hours=3),
        "quarters": [m15(i, "86", "86.6", "85.9", "86.5") for i in range(8)],
        "hours": [candle(i, 86, 87, 85.5, 86.5) for i in range(6)],
        "checks": (STALL,),
    }
    return TradeFacts(**{**values, **changes})


def test_the_facts_are_short_and_every_number_is_in_r_from_the_entry() -> None:
    text = render_facts(facts())
    assert text.startswith("<facts>") and text.endswith("</facts>")
    assert "stop now 82.1 (-1.00R)" in text
    assert "T1 88.1 (+2.00R) filled; T2 90.1 (+3.00R)" in text
    assert "best since entry +2.10R, set 2h 30m ago" in text and "open 1d 3h" in text
    assert "checks: stall past +1R" in text
    assert "-0.042R (stall exit)" in text, "the docs/37 result for this strategy"
    # Roughly 4 characters a token: the facts stay well under the 2,300 input tokens planned.
    assert len(text) < 2000
    assert len(PROMPT_BODY) > 2600, "long enough for Haiku's 512-token cache minimum"
    short = render_facts(facts(side=Side.SHORT, stop=D("86.10"), price=D("83.10")))
    assert "stop now 86.1 (-1.00R)" in short and "price now 83.1 (+0.50R)" in short


def test_advice_is_one_of_three_actions_with_one_short_sentence() -> None:
    assert ExitAdvice(action="hold", reason="Trend intact.").action == "hold"
    for bad in (
        {"action": "sell_more", "reason": "x"},
        {"action": "hold", "reason": ""},
        {"action": "hold", "reason": "y" * 301},
        {"action": "hold", "reason": "see https://example.com"},
        {"action": "take_profit_now", "reason": "x", "stop": 90},
    ):
        with pytest.raises(ValidationError):
            ExitAdvice.model_validate(bad)


def api_reply(content: str, stop_reason: str = "end_turn") -> dict[str, object]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": MODEL,
        "content": [{"type": "text", "text": content}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": 700,
            "output_tokens": 60,
            "cache_read_input_tokens": 560,
            "cache_creation_input_tokens": 0,
        },
    }


class FakeAnthropic:
    """A transport that answers locally, so no request can leave this computer."""

    def __init__(self, reply: dict[str, object]) -> None:
        self.reply = reply
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return httpx2.Response(200, json=self.reply)

    def reviewer(self) -> ClaudeExitReviewer:
        http = httpx2.AsyncClient(transport=httpx2.MockTransport(self))
        return ClaudeExitReviewer(
            anthropic.AsyncAnthropic(api_key="test-key", max_retries=0, http_client=http)
        )


async def test_the_real_sdk_call_asks_haiku_with_cached_instructions() -> None:
    advice = json.dumps({"action": "take_profit_now", "reason": "Rejected at T2 twice."})
    fake = FakeAnthropic(api_reply(advice))
    result = await fake.reviewer().review("<facts>test</facts>")
    assert result.status == "advised" and result.advice is not None
    assert result.advice.action == "take_profit_now"
    assert result.usage.cache_read_tokens == 560
    sent = json.loads(fake.requests[0].content)
    assert sent["model"] == "claude-haiku-5-5" and sent["max_tokens"] == 1024
    assert sent["output_config"]["effort"] == "low" and "format" in sent["output_config"]
    assert sent["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert sent["messages"] == [{"role": "user", "content": "<facts>test</facts>"}]
    assert "tools" not in sent


async def test_refusals_truncation_and_extra_fields_are_not_advice() -> None:
    refused = await FakeAnthropic(api_reply("", "refusal")).reviewer().review("x")
    assert refused.status == "refused" and refused.usage.output_tokens == 60
    cut = await FakeAnthropic(api_reply('{"action": "ho', "max_tokens")).reviewer().review("x")
    assert cut.status == "invalid" and cut.advice is None
    sneaky = json.dumps({"action": "hold", "reason": "ok", "new_stop": 1})
    assert (await FakeAnthropic(api_reply(sneaky)).reviewer().review("x")).status == "invalid"


def m1(minute: int, open_: str, high: str, low: str, close: str) -> ClosedCandle:
    return candle(minute, float(open_), float(high), float(low), float(close), 5000.0, Timeframe.M1)


def open_trade(**changes: Any) -> OpenTrade:
    values: dict[str, Any] = {
        "position_id": uuid4(),
        "recommendation_id": uuid4(),
        "account_id": uuid4(),
        "provider_id": 1,
        "instrument_id": 1,
        "side": Side.LONG,
        "entry_type": EntryType.MARKET,
        "entry": D("100.00"),
        "stop": D("98.00"),
        "targets": (D("104.00"),),
        "allocation": (D(1),),
        "quantity": D(10),
        "created_at": START - timedelta(milliseconds=1),
        "expires_at": START + timedelta(hours=1),
        "state": SignalState.ACTIVE,
        "inputs": {
            "tick": "0.01",
            "lot_step": "0.001",
            "taker_fee": "0.001",
            "maker_fee": "0.0002",
            "half_spread": "0.01",
            "entry_slippage": "0.02",
            "stop_slippage": "0.05",
        },
    }
    return OpenTrade(**{**values, **changes})


# A rise to +1.4R, then a fall to the stop. Test data, not market data.
PATH = [
    m1(0, "100", "100.2", "99.9", "100.1"),
    m1(1, "100.1", "102.9", "100.1", "102.8"),
    m1(2, "102.8", "102.9", "102.0", "102.1"),
    m1(3, "102.1", "102.2", "97.5", "97.6"),
]


def ask_after(minute: int) -> datetime:
    return PATH[minute].close_time


def test_the_replay_tracks_the_best_after_the_entry_minute() -> None:
    replayed = replay_trade(open_trade(), PATH, (), until=PATH[2].close_time)
    assert replayed.simulator.entry_fill == D("100.03")
    assert replayed.best == D("102.9") and replayed.best_at == PATH[1].close_time
    assert replayed.worst == D("100.1")


def test_taking_the_profit_exits_at_the_next_open_and_is_scored_against_the_stop() -> None:
    trade = open_trade()
    own = replay_trade(trade, PATH, ())
    assert own.simulator.fills[-1].kind == "stop"
    advised = replay_trade(trade, PATH, (), advice=(ask_after(1), "take_profit_now"))
    exit_fill = advised.simulator.fills[-1]
    assert exit_fill.kind == "exit" and exit_fill.price == D("102.74")  # Open less 0.06.
    assert r_of(trade, advised) > D(1) > D(0) > r_of(trade, own)


def test_a_breakeven_stop_counts_from_the_next_candle() -> None:
    trade = open_trade()
    advised = replay_trade(trade, PATH, (), advice=(ask_after(1), "stop_to_breakeven"))
    stop = advised.simulator.fills[-1]
    assert stop.kind == "stop" and stop.price == D("100.24")  # 100.30 less 0.06.
    assert D(0) <= r_of(trade, advised) < D("0.05"), "about breakeven after costs"


def test_hold_advice_replays_exactly_as_the_trade_did() -> None:
    trade = open_trade()
    held = replay_trade(trade, PATH, (), advice=(ask_after(1), "hold"))
    assert held.simulator.fills == replay_trade(trade, PATH, ()).simulator.fills


def test_stored_prices_lose_their_18_places_and_a_short_reads_worst_then_best() -> None:
    """Regression: the first live facts showed 85.705000000000000000 (2026-11-11)."""
    stored = D("84.100000000000000000")
    text = render_facts(
        facts(
            side=Side.SHORT,
            entry=stored,
            stop=D("86.100000000000000000"),
            targets=(D("80.100000000000000000"),),
            targets_hit=0,
            price=D("83.100000000000000000"),
            quarters=[m15(0, "84.1", "85.1", "83.1", "84.1")],
        )
    )
    assert "entry 84.1, stop now 86.1 (-1.00R), targets T1 80.1 (+2.00R)" in text
    assert "000000" not in text
    # A short's worst is the candle's high, -0.50R here, and its best the low, +0.50R.
    assert "open worst best close: +0.00R -0.50R +0.50R +0.00R" in text
