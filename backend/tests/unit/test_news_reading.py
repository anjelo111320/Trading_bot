"""The news signal's pre-registered rule (D055, docs/39). Test data, not market data."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from typing import Any
from uuid import uuid7

import pytest

from trading_intel.domain.signals import Side
from trading_intel.news_intelligence.reading import (
    RULE_VERSION,
    THRESHOLD,
    WINDOW,
    LabelledStory,
    NewsSignal,
    alignment,
    read_news,
)

AT = datetime(2026, 11, 11, 12, tzinfo=UTC)


def story(sentiment: str = "bearish", impact: str = "medium", **changes: Any) -> LabelledStory:
    values: dict[str, Any] = {
        "article_id": uuid7(),
        "headline": "Bitcoin ETFs shed $1.3B in biggest weekly outflow",
        "published_at": AT - timedelta(hours=1),
        "sentiment": sentiment,
        "impact": impact,
        "possibly_misleading": False,
        "relevance": D("0.9"),
    }
    return LabelledStory(**{**values, **changes})


def test_the_rule_is_fixed_before_any_reading_is_scored() -> None:
    assert RULE_VERSION == 1 and timedelta(hours=12) == WINDOW and D("1.5") == THRESHOLD


def test_one_medium_story_naming_the_coin_sets_the_direction() -> None:
    reading = read_news([story("bearish", "medium")], AT)
    assert reading.direction == "bearish" and reading.score == D("-1.8")
    assert read_news([story("bullish", "medium")], AT).direction == "bullish"


def test_one_low_story_or_a_macro_story_alone_is_not_enough() -> None:
    assert read_news([story("bullish", "low")], AT).direction == "neutral"  # 0.9
    macro = story("bearish", "high", relevance=D("0.4"))  # 1.2
    assert read_news([macro], AT).score == D("-1.2")
    assert read_news([macro], AT).direction == "neutral"


def test_opposite_stories_cancel_and_neutral_stories_add_nothing() -> None:
    stories = [story("bullish", "high"), story("bearish", "high"), story("neutral", "high")]
    reading = read_news(stories, AT)
    assert reading.score == 0 and reading.direction == "neutral"
    assert len(reading.stories) == 3


def test_misleading_stories_and_stories_outside_the_window_do_not_count() -> None:
    old = story(published_at=AT - WINDOW)
    later = story(published_at=AT + timedelta(seconds=1))
    flagged = story(possibly_misleading=True)
    reading = read_news([old, later, flagged], AT)
    assert reading.stories == () and reading.direction == "neutral"
    just_inside = story(published_at=AT - WINDOW + timedelta(seconds=1))
    assert read_news([just_inside], AT).direction == "bearish"


def test_a_trade_with_the_news_is_aligned_against_it_conflicting() -> None:
    bearish = read_news([story("bearish", "high")], AT)
    assert alignment(Side.SHORT, bearish) == "aligned"
    assert alignment(Side.LONG, bearish) == "conflicting"
    quiet = read_news([], AT)
    assert alignment(Side.LONG, quiet) == "neutral" and alignment(Side.SHORT, quiet) == "neutral"


def test_the_stored_context_shows_what_made_the_reading() -> None:
    counted = story("bullish", "high")
    context = read_news([counted], AT).context()
    assert context["rule_version"] == 1 and context["direction"] == "bullish"
    assert context["score"] == "2.7" and context["at"] == AT.isoformat()
    assert context["stories"] == [
        {
            "article_id": str(counted.article_id),
            "sentiment": "bullish",
            "impact": "high",
            "relevance": "0.9",
            "weight": "2.7",
        }
    ]


class Stories:
    def __init__(self, stories: list[LabelledStory]) -> None:
        self.stories = stories
        self.asked: list[tuple[int, datetime, datetime]] = []

    async def labelled_stories(
        self, instrument_id: int, at: datetime, since: datetime
    ) -> list[LabelledStory]:
        self.asked.append((instrument_id, at, since))
        return self.stories


@pytest.mark.parametrize(
    ("side", "expected"), [(Side.LONG, "aligned"), (Side.SHORT, "conflicting")]
)
async def test_the_signal_asks_only_for_the_window_before_the_moment(
    side: Side, expected: str
) -> None:
    source = Stories([story("bullish", "medium")])
    found, context = await NewsSignal(source).alignment(7, side, AT)
    assert found == expected and context["direction"] == "bullish"
    assert source.asked == [(7, AT, AT - WINDOW)]
