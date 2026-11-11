"""The news signal on real PostgreSQL (D055): readings never use what came later, each story
counts once, readings are kept per 4H close, and a signal stores the news beside it."""

from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.test_api_forecasts import logged_in
from tests.integration.test_news_pipeline import NOW, FakeClassifier, pipeline, rows, seeded
from trading_intel.database.repositories.news import NewsRepository
from trading_intel.domain.instruments import Instrument
from trading_intel.news_intelligence.classifier import ClassifierResult, NewsAssessment, Usage
from trading_intel.news_intelligence.reading import NewsSignal

pytestmark = pytest.mark.integration

__all__ = ["seeded"]  # The news pipeline's fixture: two Fed copies of one story, and a bakery.

LABELLED = NOW + timedelta(hours=3)  # When the pipeline below runs and labels the story.


class BearishClassifier(FakeClassifier):
    async def classify(self, headline: str, snippet: str | None) -> ClassifierResult:
        self.calls += 1
        assessment = NewsAssessment(
            event_type="monetary_policy",
            sentiment="bearish",
            potential_impact="high",
            certainty="confirmed",
            possibly_misleading=False,
            summary="The central bank held rates.",
        )
        return ClassifierResult("valid", assessment, "claude-haiku-5-5", Usage(1000, 100))


def bitcoin(instruments: list[Instrument]) -> Instrument:
    return next(item for item in instruments if item.symbol == "BTCUSDT")


async def test_a_story_counts_once_and_only_after_it_was_seen_and_labelled(
    seeded: tuple[AsyncEngine, list[Instrument]],
) -> None:
    engine, instruments = seeded
    await pipeline(engine, instruments, BearishClassifier()).run_once()
    signal = NewsSignal(NewsRepository(engine))
    btc = bitcoin(instruments).id
    before_label = await signal.reading(btc, LABELLED - timedelta(seconds=1))
    assert before_label.stories == () and before_label.score == 0
    after = await signal.reading(btc, LABELLED)
    # Two copies of the Fed story, one label: high impact and bearish. One copy's snippet names
    # BTC, so the story keeps that copy's direct relevance (0.9), not the macro 0.4.
    assert len(after.stories) == 1 and after.score == D("-2.7")
    assert after.direction == "bearish"
    # Both copies were published 12 hours or more before this.
    gone = await signal.reading(btc, NOW + timedelta(hours=13))
    assert gone.stories == ()


async def test_each_coin_and_4h_close_keeps_one_reading(
    seeded: tuple[AsyncEngine, list[Instrument]],
) -> None:
    engine, instruments = seeded
    await pipeline(engine, instruments, BearishClassifier()).run_once()
    news = NewsRepository(engine)
    btc = bitcoin(instruments).id
    close = NOW + timedelta(hours=4) - timedelta(milliseconds=1)
    reading = await NewsSignal(news).reading(btc, close)
    assert await news.record_reading(btc, close, D("70123.4"), reading)
    assert not await news.record_reading(btc, close, D("70000"), reading), "kept as it was"
    [row] = await rows("SELECT direction, score, stories, close_price, context FROM news_readings")
    assert row["direction"] == "bearish" and row["score"] == D("-2.7") and row["stories"] == 1
    assert row["close_price"] == D("70123.4")
    assert '"rule_version": 1' in row["context"]


@pytest.fixture
def api(clean_database: None, tmp_path: Path) -> Iterator[TestClient]:
    yield from logged_in(tmp_path, kronos=False)


def test_the_api_gives_a_coins_reading_now_labelled_untested(api: TestClient) -> None:
    response = api.get("/api/v1/news/signal", params={"instrument_id": 1})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["untested"] is True and body["rule_version"] == 1
    assert body["direction"] == "neutral" and body["score"] == "0" and body["stories"] == []
    assert body["threshold"] == "1.5" and body["window_hours"] == 12
