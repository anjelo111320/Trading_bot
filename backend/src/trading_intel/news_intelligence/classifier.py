"""Classify one news item with Claude. Output can describe an item and do nothing else.

The schema holds labels and one sentence, so even a successful prompt injection has nothing
to act through: no prices, no actions, no tools. It reaches no other module.
"""

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Final, Literal, Protocol

import anthropic
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from trading_intel.news_intelligence.normalize import clean_text

MODEL: Final = "claude-haiku-5-5"
EFFORT: Final = "low"
MAX_TOKENS: Final = 300
PROMPT_NAME: Final = "news_classify"
PROMPT_VERSION: Final = 1
OUTPUT_SCHEMA_VERSION: Final = 1
PROMPT_BODY: Final = (Path(__file__).parent / "prompts" / "classify_v1.txt").read_text()
PROMPT_SHA256: Final = hashlib.sha256(PROMPT_BODY.encode()).hexdigest()
MAX_SUMMARY: Final = 400

EventType = Literal[
    "monetary_policy",
    "inflation",
    "employment",
    "geopolitical",
    "regulation",
    "company_earnings",
    "exchange_announcement",
    "network_incident",
    "token_unlock",
    "security_incident",
    "other",
]


class NewsAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: EventType
    sentiment: Literal["bullish", "bearish", "neutral"]
    potential_impact: Literal["low", "medium", "high"]
    certainty: Literal["confirmed", "reported", "speculation"]
    possibly_misleading: bool
    summary: str

    @field_validator("summary")
    @classmethod
    def _plain_summary(cls, value: str) -> str:
        cleaned = clean_text(value)
        if not cleaned or len(cleaned) > MAX_SUMMARY:
            raise ValueError("summary must be one short sentence")
        if "http://" in cleaned or "https://" in cleaned:
            raise ValueError("summary must not contain links")
        return cleaned


OUTPUT_SCHEMA: Final = anthropic.transform_schema(NewsAssessment)


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_5m_tokens: int = 0


@dataclass(frozen=True)
class ClassifierResult:
    status: Literal["valid", "invalid", "refused"]
    assessment: NewsAssessment | None
    model: str
    usage: Usage


class Classifier(Protocol):
    async def classify(self, headline: str, snippet: str | None) -> ClassifierResult: ...


def article_block(headline: str, snippet: str | None) -> str:
    """Closing tags inside the text are neutralised, so an item cannot break out of its block."""
    body = f"Headline: {clean_text(headline)}\nSnippet: {clean_text(snippet or '')}"
    safe = body.replace("<", "(").replace(">", ")")
    return f"<untrusted_article>\n{safe}\n</untrusted_article>"


def cost_usd(usage: Usage, prices: dict[str, Decimal]) -> Decimal:
    million = Decimal(1_000_000)
    return (
        Decimal(usage.input_tokens) * prices["input"]
        + Decimal(usage.output_tokens) * prices["output"]
        + Decimal(usage.cache_read_tokens) * prices["cache_read"]
        + Decimal(usage.cache_write_5m_tokens) * prices["cache_write_5m"]
    ) / million


def _usage_of(response: Any) -> Usage:
    usage = response.usage
    return Usage(
        input_tokens=usage.input_tokens or 0,
        output_tokens=usage.output_tokens or 0,
        cache_read_tokens=usage.cache_read_input_tokens or 0,
        cache_write_5m_tokens=usage.cache_creation_input_tokens or 0,
    )


class ClaudeClassifier:
    """Uses the official SDK. The key stays on the server and is never logged."""

    def __init__(self, client: anthropic.AsyncAnthropic) -> None:
        self._client = client

    async def classify(self, headline: str, snippet: str | None) -> ClassifierResult:
        """Validation happens here, so usage is recorded even for a reply that is refused."""
        response = await self._client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=PROMPT_BODY,
            messages=[{"role": "user", "content": article_block(headline, snippet)}],
            output_config={
                "effort": EFFORT,
                "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
            },
        )
        usage = _usage_of(response)
        if response.stop_reason == "refusal":
            return ClassifierResult("refused", None, response.model, usage)
        text = next((block.text for block in response.content if block.type == "text"), "")
        try:
            assessment = NewsAssessment.model_validate_json(text)
        except ValidationError:
            return ClassifierResult("invalid", None, response.model, usage)
        if response.stop_reason != "end_turn":
            return ClassifierResult("invalid", None, response.model, usage)
        return ClassifierResult("valid", assessment, response.model, usage)
