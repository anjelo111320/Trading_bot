"""Claude's view on an open paper trade, in shadow mode (D051, docs/38).

Python decides when to ask and calculates every number. Claude answers with one of three
actions and one sentence. Nothing here can place an order, move a stop or change a fill:
the answer is only stored, and scored when the trade closes.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Final, Literal, Protocol

import anthropic
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from trading_intel.domain.candles import ClosedCandle
from trading_intel.domain.signals import Side
from trading_intel.news_intelligence.classifier import Usage
from trading_intel.news_intelligence.normalize import clean_text

MODEL: Final = "claude-haiku-5-5"  # The owner's choice for now (D051).
EFFORT: Final = "low"
MAX_TOKENS: Final = 1024
PROMPT_NAME: Final = "exit_review"
PROMPT_VERSION: Final = 1
OUTPUT_SCHEMA_VERSION: Final = 1
PROMPT_BODY: Final = (Path(__file__).parent / "prompts" / "exit_v1.txt").read_text()
PROMPT_SHA256: Final = hashlib.sha256(PROMPT_BODY.encode()).hexdigest()
MAX_REASON: Final = 300

ExitAction = Literal["hold", "take_profit_now", "stop_to_breakeven"]

# What docs/37 measured for fixed early-exit rules, per strategy, so Claude weighs it.
BACKTEST_NOTES: Final = {
    "daily_trend": (
        "over 344 trades from 2020 to 2025, fixed rules changed the result by -0.023R "
        "(breakeven at +1R), -0.028R (stall exit) and +0.009R (swing trail) a trade; "
        "none helped clearly. Its exit is a 10-day trailing stop, and its target is a far cap"
    ),
    "pattern_breakout": (
        "over 790 trades from 2020 to 2025, fixed rules changed the result by -0.005R "
        "(breakeven at +1R), -0.042R (stall exit) and -0.001R (swing trail) a trade; "
        "taking profit early gave up as much on winners as it saved on losers"
    ),
    "fvg_choch": (
        "over 255 trades from 2020 to 2025, fixed rules changed the result by -0.073R "
        "(breakeven at +1R), -0.034R (stall exit) and -0.068R (swing trail) a trade"
    ),
}
NO_NOTE: Final = "early-exit rules were not tested for this strategy, which has no history test"


class ExitAdvice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ExitAction
    reason: str

    @field_validator("reason")
    @classmethod
    def _one_sentence(cls, value: str) -> str:
        cleaned = clean_text(value)
        if not cleaned or len(cleaned) > MAX_REASON:
            raise ValueError("reason must be one short sentence")
        if "http://" in cleaned or "https://" in cleaned:
            raise ValueError("reason must not contain links")
        return cleaned


OUTPUT_SCHEMA: Final = anthropic.transform_schema(ExitAdvice)


@dataclass(frozen=True)
class ReviewResult:
    status: Literal["advised", "invalid", "refused"]
    advice: ExitAdvice | None
    model: str
    usage: Usage
    reply: str


class ExitReviewer(Protocol):
    async def review(self, facts: str) -> ReviewResult: ...


@dataclass(frozen=True)
class TradeFacts:
    """An open trade at a 15M close, as Python calculated it from closed candles."""

    symbol: str
    strategy: str
    account: str
    side: Side
    entry: Decimal  # The entry fill.
    risk: Decimal  # Planned risk per unit: the planned entry to the first stop.
    stop: Decimal  # The stop now.
    targets: tuple[Decimal, ...]
    targets_hit: int
    price: Decimal  # This 15M close.
    best: Decimal
    worst: Decimal
    best_age: timedelta
    open_for: timedelta
    quarters: Sequence[ClosedCandle]  # The last 8 15M candles.
    hours: Sequence[ClosedCandle]  # The last 6 1H candles.
    checks: tuple[str, ...]

    def r(self, price: Decimal) -> str:
        value = self.side.sign * (price - self.entry) / self.risk
        return f"{abs(value) if value == 0 else value:+.2f}R"  # A short at its entry is not -0.


def _duration(span: timedelta) -> str:
    minutes = int(span.total_seconds() // 60)
    days, rest = divmod(minutes, 1440)
    hours, minutes = divmod(rest, 60)
    return f"{days}d {hours}h" if days else f"{hours}h {minutes}m"


def _price(value: Decimal) -> str:
    """Without the 18 places prices are stored with, which only cost tokens."""
    return format(value.normalize(), "f")


def render_facts(facts: TradeFacts) -> str:
    """The one block Claude is shown. Every number in it comes from Python."""

    def bars(candles: Sequence[ClosedCandle]) -> str:
        # Worst and best for this trade, so a short reads the same way as a long.
        long = facts.side is Side.LONG
        return " | ".join(
            " ".join(
                facts.r(price)
                for price in (c.open, c.low if long else c.high, c.high if long else c.low, c.close)
            )
            for c in candles
        )

    targets = "; ".join(
        f"T{index + 1} {_price(target)} ({facts.r(target)})"
        f"{' filled' if index < facts.targets_hit else ''}"
        for index, target in enumerate(facts.targets)
    )
    note = BACKTEST_NOTES.get(facts.strategy, NO_NOTE)
    return "\n".join(
        [
            "<facts>",
            f"coin {facts.symbol}, strategy {facts.strategy}, {facts.side.value} in the "
            f"{facts.account} paper account",
            f"checks: {', '.join(facts.checks)}",
            f"entry {_price(facts.entry)}, stop now {_price(facts.stop)} "
            f"({facts.r(facts.stop)}), targets {targets}",
            f"price now {_price(facts.price)} ({facts.r(facts.price)}); best since entry "
            f"{facts.r(facts.best)}, set {_duration(facts.best_age)} ago; worst "
            f"{facts.r(facts.worst)}; open {_duration(facts.open_for)}",
            f"last 15M candles, open worst best close: {bars(facts.quarters)}",
            f"last 1H candles, open worst best close: {bars(facts.hours)}",
            f"backtest note: {note}",
            "</facts>",
        ]
    )


def _usage_of(response: Any) -> Usage:
    usage = response.usage
    return Usage(
        input_tokens=usage.input_tokens or 0,
        output_tokens=usage.output_tokens or 0,
        cache_read_tokens=usage.cache_read_input_tokens or 0,
        cache_write_5m_tokens=usage.cache_creation_input_tokens or 0,
    )


class ClaudeExitReviewer:
    """Uses the official SDK. The key stays on the server and is never logged."""

    def __init__(self, client: anthropic.AsyncAnthropic) -> None:
        self._client = client

    async def review(self, facts: str) -> ReviewResult:
        """Validation happens here, so usage is recorded even for a reply that is refused."""
        response = await self._client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            # The instructions never change, so trades checked at one close share the cache.
            system=[{"type": "text", "text": PROMPT_BODY, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": facts}],
            output_config={
                "effort": EFFORT,
                "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
            },
        )
        usage = _usage_of(response)
        text = next((block.text for block in response.content if block.type == "text"), "")
        if response.stop_reason == "refusal":
            return ReviewResult("refused", None, response.model, usage, text)
        if response.stop_reason != "end_turn":
            return ReviewResult("invalid", None, response.model, usage, text)
        try:
            advice = ExitAdvice.model_validate_json(text)
        except ValidationError:
            return ReviewResult("invalid", None, response.model, usage, text)
        return ReviewResult("advised", advice, response.model, usage, text)
