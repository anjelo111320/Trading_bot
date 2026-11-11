"""The dashboard's view of Claude's exit advice (D051). Read-only, and it never calls Claude."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import make_settings
from tests.integration.test_api_forecasts import logged_in
from trading_intel.api.app import create_app

pytestmark = pytest.mark.integration

REVIEWS = "/api/v1/ai/exit-reviews"


@pytest.fixture
def api(clean_database: None, tmp_path: Path) -> Iterator[TestClient]:
    yield from logged_in(tmp_path, kronos=False)


def test_before_any_check_the_view_is_empty_and_labelled_shadow(api: TestClient) -> None:
    response = api.get(REVIEWS)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["shadow"] is True and body["model"] == "claude-haiku-5-5"
    assert body["asking"] is False, "the test settings hold no Anthropic key"
    assert body["reviews"] == [] and body["statuses"] == {} and body["cost_usd"] == "0.0000"
    assert body["mean_change_r"] is None


def test_the_view_needs_the_owner(clean_database: None) -> None:
    with TestClient(create_app(make_settings()), base_url="http://127.0.0.1") as anonymous:
        assert anonymous.get(REVIEWS).status_code == 401
