"""Claude's daily cost limit on the dashboard (D062): shown with today's spend, changed only
from the dashboard, logged, and never above its ceiling. Nothing here calls Claude."""

import asyncio
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.conftest import make_settings
from tests.integration.test_api_forecasts import EMAIL, ORIGIN, logged_in
from trading_intel.database.engine import create_engine
from trading_intel.database.repositories.news import NewsRepository

pytestmark = pytest.mark.integration

BUDGET = "/api/v1/ai/budget"


@pytest.fixture
def api(clean_database: None, tmp_path: Path) -> Iterator[TestClient]:
    yield from logged_in(tmp_path, kronos=False)


async def spend(purpose: str, cost: str, input_tokens: int, output_tokens: int) -> None:
    engine = create_engine(make_settings().database_url)
    await NewsRepository(engine).record_usage(
        purpose, "claude-haiku-5-5", input_tokens, output_tokens, 0, 0, Decimal(cost)
    )
    await engine.dispose()


async def audit() -> list[Any]:
    engine = create_engine(make_settings().database_url)
    async with engine.connect() as connection:
        rows = (
            await connection.execute(
                text("SELECT actor, after FROM audit_log WHERE action = 'ai_daily_limit_changed'")
            )
        ).all()
    await engine.dispose()
    return [dict(row._mapping) for row in rows]


def test_the_limit_is_shown_with_todays_spend_by_purpose(api: TestClient) -> None:
    body = api.get(BUDGET).json()
    assert body["daily_limit_usd"] == "0.5" and body["ceiling_usd"] == "3"
    assert body["spent_today_usd"] == "0" and body["reached"] is False
    asyncio.run(spend("news_classification", "0.0002", 1000, 120))
    asyncio.run(spend("exit_review", "0.0003", 600, 150))
    asyncio.run(spend("exit_review", "0.0001", 500, 100))
    body = api.get(BUDGET).json()
    assert body["spent_today_usd"] == "0.0006" and body["calls_today"] == 3
    assert body["input_tokens_today"] == 2100 and body["output_tokens_today"] == 370
    purposes = {item["purpose"]: (item["calls"], item["cost_usd"]) for item in body["by_purpose"]}
    assert purposes == {"exit_review": (2, "0.0004"), "news_classification": (1, "0.0002")}


def test_the_limit_changes_only_from_the_dashboard_within_its_ceiling(api: TestClient) -> None:
    api.get(BUDGET)
    assert api.put(BUDGET, json={"daily_limit_usd": "0.25"}).status_code == 403
    elsewhere = {"Origin": "https://example.invalid"}
    assert api.put(BUDGET, json={"daily_limit_usd": "0.25"}, headers=elsewhere).status_code == 403
    for bad in ("3.01", "-0.1"):
        response = api.put(BUDGET, json={"daily_limit_usd": bad}, headers={"Origin": ORIGIN})
        assert response.status_code == 400, bad
    assert api.get(BUDGET).json()["daily_limit_usd"] == "0.5", "nothing was saved"
    saved = api.put(BUDGET, json={"daily_limit_usd": "0.25"}, headers={"Origin": ORIGIN})
    assert saved.status_code == 200, saved.text
    assert saved.json()["daily_limit_usd"] == "0.25" and saved.json()["changed_at"] is not None
    [logged] = asyncio.run(audit())
    assert logged["actor"] == EMAIL
    assert logged["after"] == {"daily_limit_usd": "0.25", "before": "0.50"}


def test_a_spent_limit_says_so(api: TestClient) -> None:
    api.get(BUDGET)
    stopped = api.put(BUDGET, json={"daily_limit_usd": "0"}, headers={"Origin": ORIGIN})
    assert stopped.json()["reached"] is True, "zero stops every call"
