"""The coin scorecard route (D068), on real PostgreSQL through the API."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.integration.test_api_forecasts import logged_in
from trading_intel.performance.scorecard import NEVER_TESTED

pytestmark = pytest.mark.integration

SCORECARD = "/api/v1/coins/scorecard"


@pytest.fixture
def api(clean_database: None, tmp_path: Path) -> Iterator[TestClient]:
    yield from logged_in(tmp_path, kronos=False)


def test_every_coin_gets_a_cell_for_every_strategy_before_any_trade(api: TestClient) -> None:
    response = api.get(SCORECARD)
    assert response.status_code == 200
    body = response.json()
    assert body["account"] == "binance", "no real account yet, so today's signals are demo's"
    coins = {coin["symbol"]: coin for coin in body["coins"]}
    assert {"BTCUSDT", "ETHUSDT"} <= set(coins)
    btc = {cell["strategy"]: cell for cell in coins["BTCUSDT"]["strategies"]}
    assert list(btc) == [
        "daily_trend",
        "pattern_breakout",
        "fvg_choch",
        "trend_break_baseline",
        "trend_break_loose",
        "news_move",
    ]
    trend = btc["daily_trend"]
    assert trend["evidence"] == {
        "trades": 71, "mean_r": "0.439", "low": "-0.03", "high": "0.98", "source": "docs/33",
    }  # fmt: skip
    assert trend["untested"] is None and not trend["left_out"]
    assert (
        btc["trend_break_baseline"]["evidence"]["source"] == "docs/42, 15-minute fills from 2023-11"
    )
    assert btc["news_move"]["untested"] == NEVER_TESTED["news_move"]
    for coin in coins.values():
        assert coin["live"] == {"entered": 0, "closed": 0, "won": 0, "mean_r": None}
        assert coin["entries"]["trades"] == 0
        assert coin["conditions"]["signals_today"] == 0
    if "HYPEUSDT" in coins:
        hype = {cell["strategy"]: cell for cell in coins["HYPEUSDT"]["strategies"]}
        assert hype["daily_trend"]["left_out"] and not hype["fvg_choch"]["left_out"]
    loose = [
        cell
        for coin in coins.values()
        for cell in coin["strategies"]
        if cell["strategy"] == "trend_break_loose"
    ]
    assert loose and all(cell["left_out"] for cell in loose), "switched off on every coin (D070)"


def test_the_scorecard_needs_the_owner(api: TestClient) -> None:
    api.cookies.clear()
    assert api.get(SCORECARD).status_code == 401
