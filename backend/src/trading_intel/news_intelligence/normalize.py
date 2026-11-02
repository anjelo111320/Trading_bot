"""Clean untrusted text and detect duplicates. Pure functions."""

import html
import re
from datetime import datetime, timedelta
from typing import Final

SAME_STORY: Final = 0.7
STORY_WINDOW: Final = timedelta(hours=48)
MAX_FIELD: Final = 2000

_TAGS = re.compile(r"<[^>]{0,500}>")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-\u200F\u202A-\u202E⁠-⁤]")
_SPACE = re.compile(r"\s+")
_WORD = re.compile(r"[a-z0-9]+")
_NOISE: Final = frozenset(
    {"a", "an", "and", "as", "at", "by", "for", "from", "in", "is", "of", "on", "or", "the", "to"}
)


def clean_text(value: str) -> str:
    """Remove markup, hidden characters and excess length. Meaning is left alone."""
    text = _TAGS.sub(" ", html.unescape(value))
    text = _CONTROL.sub("", text)
    return _SPACE.sub(" ", text).strip()[:MAX_FIELD]


def fingerprint(headline: str) -> frozenset[str]:
    return frozenset(word for word in _WORD.findall(headline.lower()) if word not in _NOISE)


def similarity(first: frozenset[str], second: frozenset[str]) -> float:
    if not first or not second:
        return 0.0
    return len(first & second) / len(first | second)


def same_story(
    headline: str, published_at: datetime, other_headline: str, other_published_at: datetime
) -> bool:
    if abs(published_at - other_published_at) > STORY_WINDOW:
        return False
    return similarity(fingerprint(headline), fingerprint(other_headline)) >= SAME_STORY
