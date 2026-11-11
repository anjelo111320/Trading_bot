"""The news signal: one reading per coin from Claude's labels on its recent stories (D055).

Claude labels each story once (sentiment, impact). Python adds the labels up here by a fixed,
versioned rule, pre-registered in docs/39-NEWS-SIGNAL.md. The reading is untested evidence: it
is stored beside every Python signal and at every 4H close so it can be tested forward, and
nothing in trading reads it, so it never changes a trade.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Literal, Protocol
from uuid import UUID

from trading_intel.domain.signals import Side

RULE_VERSION: Final = 1
# Stories published within this window before the reading count, once seen and labelled.
WINDOW: Final = timedelta(hours=12)
# About one medium-impact story naming the coin, or one high-impact story about crypto.
THRESHOLD: Final = Decimal("1.5")
IMPACT_WEIGHTS: Final[dict[str, Decimal]] = {
    "low": Decimal(1),
    "medium": Decimal(2),
    "high": Decimal(3),
}
SIGNS: Final[dict[str, int]] = {"bullish": 1, "bearish": -1, "neutral": 0}

Direction = Literal["bullish", "bearish", "neutral"]
Alignment = Literal["aligned", "conflicting", "neutral", "unavailable"]


@dataclass(frozen=True)
class LabelledStory:
    """One story about a coin, as it could be known at the reading's time."""

    article_id: UUID
    headline: str
    published_at: datetime
    sentiment: str
    impact: str
    possibly_misleading: bool
    relevance: Decimal  # How directly the story names the coin, from 0 to 1.

    @property
    def weight(self) -> Decimal:
        """Signed: positive for bullish, negative for bearish, zero for neutral."""
        return SIGNS[self.sentiment] * IMPACT_WEIGHTS[self.impact] * self.relevance


@dataclass(frozen=True)
class NewsReading:
    at: datetime
    direction: Direction
    score: Decimal
    stories: tuple[LabelledStory, ...]  # Only those counted, newest first.

    def context(self) -> dict[str, Any]:
        """What the reading was made of, stored with it so it can be checked later."""
        return {
            "rule_version": RULE_VERSION,
            "at": self.at.isoformat(),
            "direction": self.direction,
            "score": str(self.score),
            "stories": [
                {
                    "article_id": str(story.article_id),
                    "sentiment": story.sentiment,
                    "impact": story.impact,
                    "relevance": str(story.relevance),
                    "weight": str(story.weight),
                }
                for story in self.stories
            ],
        }


def read_news(stories: Sequence[LabelledStory], at: datetime) -> NewsReading:
    """Sum the signed weights of stories published in the window before `at`.

    A story Claude flagged as possibly misleading does not count. The caller passes only
    stories seen and labelled by `at`, so nothing from after it is used.
    """
    counted = tuple(
        sorted(
            (
                story
                for story in stories
                if not story.possibly_misleading and at - WINDOW < story.published_at <= at
            ),
            key=lambda story: story.published_at,
            reverse=True,
        )
    )
    score = sum((story.weight for story in counted), Decimal(0))
    direction: Direction = (
        "bullish" if score >= THRESHOLD else "bearish" if score <= -THRESHOLD else "neutral"
    )
    return NewsReading(at, direction, score, counted)


def alignment(side: Side, reading: NewsReading) -> Alignment:
    """Whether the news agrees with a trade's direction. Neutral news is neither."""
    if reading.direction == "neutral":
        return "neutral"
    agrees = (reading.direction == "bullish") == (side is Side.LONG)
    return "aligned" if agrees else "conflicting"


class StorySource(Protocol):
    async def labelled_stories(
        self, instrument_id: int, at: datetime, since: datetime
    ) -> list[LabelledStory]: ...


class NewsSignal:
    """Readings from stored stories, as they could be known at each moment."""

    def __init__(self, stories: StorySource) -> None:
        self._stories = stories

    async def reading(self, instrument_id: int, at: datetime) -> NewsReading:
        return read_news(await self._stories.labelled_stories(instrument_id, at, at - WINDOW), at)

    async def alignment(
        self, instrument_id: int, side: Side, at: datetime
    ) -> tuple[Alignment, dict[str, Any]]:
        reading = await self.reading(instrument_id, at)
        return alignment(side, reading), reading.context()
