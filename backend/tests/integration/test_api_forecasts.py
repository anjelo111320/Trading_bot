"""The forecast view through real HTTP handling, with a stand-in model and seeded candles.

The stand-in writes fixed test paths, and every candle here is constructed test data.
"""

import asyncio
import json
import threading
from collections.abc import Iterator, Sequence
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import make_settings
from tests.integration.test_forecasts import StandInModel
from tests.quant_data import candle
from trading_intel.api.app import create_app
from trading_intel.core.clock import FixedClock
from trading_intel.database.engine import create_engine
from trading_intel.database.repositories.candles import CandleRepository
from trading_intel.database.repositories.forecasts import ForecastRepository
from trading_intel.database.repositories.operations import RuleRepository
from trading_intel.database.repositories.reference import ReferenceRepository
from trading_intel.domain.base import DataOrigin
from trading_intel.domain.candles import ClosedCandle, Timeframe
from trading_intel.domain.instruments import InstrumentRules
from trading_intel.forecasting.kronos import ModelForecast
from trading_intel.forecasting.service import ForecastService
from trading_intel.forecasting.time_machine import TimeMachineParameters

pytestmark = pytest.mark.integration

EMAIL = "owner@example.test"
PASSWORD = "a-long-test-password"
ORIGIN = "http://127.0.0.1:3000"
HOURS = 1500


def walk(timeframe: Timeframe, count: int, provider: int, instrument: int) -> list[ClosedCandle]:
    rows, previous = [], 100.0
    for index in range(count):
        close = 100.0 + (index % 9) - (index % 4) + index * 0.01
        row = candle(
            index,
            previous,
            max(previous, close) + 1,
            min(previous, close) - 1,
            close,
            50.0,
            timeframe,
        )
        rows.append(
            row.model_copy(
                update={
                    "provider_id": provider,
                    "instrument_id": instrument,
                    "data_origin": DataOrigin.BACKFILL,
                }
            )
        )
        previous = close
    return rows


async def seed() -> tuple[int, int, str, ClosedCandle]:
    """Candles on four timeframes, rules, and one stored forecast from the last 1H close."""
    ingest = create_engine(make_settings().ingest_database_url)
    listed = await ReferenceRepository(ingest).provider_instruments("binance_usdm")
    provider, instrument = listed[0].provider_id, listed[0].instrument.id
    hours = walk(Timeframe.H1, HOURS, provider, instrument)
    candles = CandleRepository(ingest)
    await candles.insert(hours)
    await candles.insert(walk(Timeframe.H4, 300, provider, instrument))
    await candles.insert(walk(Timeframe.D1, 120, provider, instrument))
    await RuleRepository(ingest).replace_current(
        provider,
        instrument,
        InstrumentRules(
            status="TRADING",
            tick_size=D("0.01"),
            lot_step=D("0.001"),
            min_qty=D("0.001"),
            max_qty=D(100000),
            min_notional=D(5),
            maintenance_margin_fraction=D("0.025"),
            raw={},
        ),
        hours[0].open_time,
    )
    await ingest.dispose()
    app = create_engine(make_settings().database_url)
    last = hours[-1]
    await ForecastService(
        CandleRepository(app),
        ForecastRepository(app),
        StandInModel(),
        FixedClock(last.close_time + timedelta(minutes=1)),
        holdout_start=last.close_time + timedelta(days=365),
        baseline=TimeMachineParameters(lookback=100, paths=200),
    ).forecast(provider, instrument, Timeframe.H1, last.close_time, "manual")
    await app.dispose()
    return provider, instrument, listed[0].instrument.symbol, last


async def seed_quarters(provider: int, instrument: int, rows: list[ClosedCandle]) -> None:
    ingest = create_engine(make_settings().ingest_database_url)
    await CandleRepository(ingest).insert(
        [r.model_copy(update={"provider_id": provider, "instrument_id": instrument}) for r in rows]
    )
    await ingest.dispose()


def write_plan(folder: Path, symbol: str, last: ClosedCandle) -> dict[str, Any]:
    close = last.close
    signal = {
        "created_at": (last.close_time + timedelta(minutes=5)).isoformat(),
        "symbol": symbol,
        "as_of": last.close_time.isoformat(),
        "plan": {
            "action": "SELL",
            "setup_grade": "B",
            "bull_case": "test case for",
            "bear_case": "test case against",
            "pre_mortem": "test pre-mortem",
            "analyst_note": "test plan",
        },
        "quote": {"bid": str(close), "ask": str(close + D("0.01"))},
        "proposal": {
            "side": "SHORT",
            "entry_type": "LIMIT",
            "entry": str(close + 2),
            "stop": str(close + 5),
            "targets": [str(close - 4), str(close - 6)],
            "expiry_candles": 4,
        },
        "risk": {
            "approved": True,
            "codes": [],
            "quantity": "1.000",
            "notional": "100",
            "max_loss": "5.50",
            "reward_risk_after_costs": ["1.0", "1.5"],
        },
    }
    (folder / f"{symbol}-2026-01-01T0000-signal.json").write_text(json.dumps(signal))
    return signal


@pytest.fixture
def api(clean_database: None, tmp_path: Path) -> Iterator[TestClient]:
    settings = make_settings(
        owner_email=EMAIL, owner_password=PASSWORD, manual_signals_dir=tmp_path
    )
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": EMAIL, "password": PASSWORD},
            headers={"Origin": ORIGIN},
        )
        assert response.status_code == 200
        yield client


def url(instrument: int) -> str:
    return f"/api/v1/forecasts/latest?provider=binance_usdm&instrument_id={instrument}"


def test_the_view_holds_the_forecast_levels_patterns_and_a_waiting_plan(
    api: TestClient, tmp_path: Path
) -> None:
    _, instrument, symbol, last = asyncio.run(seed())
    write_plan(tmp_path, symbol, last)
    response = api.get(url(instrument))
    assert response.status_code == 200, response.text
    view = response.json()
    assert view["label"] == "unvalidated model forecast"
    assert view["symbol"] == symbol and view["reason"] == "manual"
    assert view["analysis_as_of"] == view["as_of"]
    assert view["baseline_rebuilt"] is True
    assert view["model_paths"] == 5 and view["baseline_paths"] == 200
    assert len(view["steps"]) == 4 and len(view["paths"]) == 5
    assert view["steps"][0]["open_time"].startswith(
        (last.open_time + timedelta(hours=1)).strftime("%Y-%m-%dT%H")
    )
    assert [h["candles"] for h in view["horizons"]] == [4]
    assert view["levels"], "the catalogue should have levels"
    for level in view["levels"]:
        assert level["position"] in ("above", "below")
        assert [r["candles"] for r in level["reach"]] == [4]
        assert "0000000" not in level["price"]
    assert view["context"]["strategies"][0]["name"] == "1H pattern breakout"
    assert view["track_record"] == {
        "resolved": 0,
        "status": "too few forecasts",
        "brier_model": None,
        "brier_baseline": None,
        "crps_model_pct": None,
        "crps_baseline_pct": None,
    }
    plan = view["plan"]
    assert plan["source"].startswith("manual analyst test")
    assert plan["side"] == "SHORT" and plan["grade"] == "B"
    assert plan["status"]["state"] == "waiting"


def test_a_plan_is_replayed_on_the_candles_that_followed(api: TestClient, tmp_path: Path) -> None:
    provider, instrument, symbol, last = asyncio.run(seed())
    signal = write_plan(tmp_path, symbol, last)
    entry, target = D(signal["proposal"]["entry"]), D(signal["proposal"]["targets"][1])
    start = last.open_time + timedelta(hours=1, minutes=15)  # The first candle after the plan.
    quarters = [
        candle(
            0,
            float(entry - 1),
            float(entry + 1),
            float(entry - 1),
            float(entry),
            100.0,
            Timeframe.M15,
        ),
        candle(
            1, float(entry), float(entry), float(target - 1), float(target), 100.0, Timeframe.M15
        ),
    ]
    shifted = [
        q.model_copy(
            update={
                "open_time": start + timedelta(minutes=15 * i),
                "close_time": Timeframe.M15.close_time(start + timedelta(minutes=15 * i)),
                "data_origin": DataOrigin.BACKFILL,
            }
        )
        for i, q in enumerate(quarters)
    ]
    asyncio.run(seed_quarters(provider, instrument, shifted))
    status = api.get(url(instrument)).json()["plan"]["status"]
    assert status["state"] == "closed"
    assert status["exit_reason"] == "tp2"
    assert status["entry_price"] == str(entry.normalize())
    assert D(status["net_pnl"]) > 0 and status["result_r"] > 0


def test_no_stored_forecast_is_a_clear_not_found(api: TestClient) -> None:
    response = api.get(url(1))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_the_view_needs_the_owner(clean_database: None) -> None:
    with TestClient(create_app(make_settings()), base_url="http://127.0.0.1") as client:
        assert client.get(url(1)).status_code == 401


def test_python_follows_the_latest_close_while_kronos_stays_put(api: TestClient) -> None:
    provider, instrument, _, last = asyncio.run(seed())
    later = [
        c.model_copy(update={"provider_id": provider, "instrument_id": instrument})
        for c in walk(Timeframe.H1, HOURS + 3, provider, instrument)[HOURS:]
    ]
    asyncio.run(seed_quarters(provider, instrument, later))
    view = api.get(url(instrument)).json()
    assert view["as_of"].startswith(last.close_time.strftime("%Y-%m-%dT%H:%M"))
    assert view["analysis_as_of"].startswith(later[-1].close_time.strftime("%Y-%m-%dT%H:%M"))
    assert D(view["analysis_close"]) == later[-1].close.normalize()


class GatedModel(StandInModel):
    """Waits for the test before answering, so a second request finds the first running."""

    def __init__(self) -> None:
        super().__init__()
        self.gate = threading.Event()

    def forecast(self, candles: Sequence[ClosedCandle]) -> ModelForecast:
        assert self.gate.wait(timeout=30)
        return super().forecast(candles)


def use_model(api: TestClient, model: StandInModel, now: Any) -> None:
    container = api.app.state.container  # type: ignore[attr-defined]
    container.forecaster = ForecastService(
        container.candles,
        container.forecasts,
        model,
        FixedClock(now),
        holdout_start=now + timedelta(days=365),
        baseline=TimeMachineParameters(lookback=100, paths=200),
    )


def finish(api: TestClient) -> dict[str, Any]:
    api.portal.call(api.app.state.container.analyses.wait)  # type: ignore[attr-defined, union-attr]
    return api.get("/api/v1/forecasts/analyse").json()


def test_reanalysis_forecasts_the_latest_close_once_at_a_time(api: TestClient) -> None:
    provider, instrument, symbol, _ = asyncio.run(seed())
    later = [
        c.model_copy(update={"provider_id": provider, "instrument_id": instrument})
        for c in walk(Timeframe.H1, HOURS + 2, provider, instrument)[HOURS:]
    ]
    asyncio.run(seed_quarters(provider, instrument, later))
    model = GatedModel()
    use_model(api, model, later[-1].close_time + timedelta(minutes=1))
    assert api.get("/api/v1/forecasts/analyse").json() == {
        "state": "idle",
        "instrument_id": None,
        "symbol": None,
        "as_of": None,
        "started_at": None,
        "finished_at": None,
        "message": None,
    }
    body = {"provider": "binance_usdm", "instrument_id": instrument}
    started = api.post("/api/v1/forecasts/analyse", json=body)
    assert started.status_code == 202
    assert started.json()["state"] == "running" and started.json()["symbol"] == symbol
    second = api.post("/api/v1/forecasts/analyse", json=body)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "conflict"
    model.gate.set()
    job = finish(api)
    assert job["state"] == "succeeded" and job["message"] is None
    assert job["as_of"].startswith(later[-1].close_time.strftime("%Y-%m-%dT%H:%M"))
    assert api.get(url(instrument)).json()["as_of"] == job["as_of"]
    again = api.post("/api/v1/forecasts/analyse", json=body)
    assert again.status_code == 202
    assert finish(api)["message"].startswith("Already analysed at this close")
    assert model.calls == 1


def test_reanalysis_reports_why_it_could_not_run(api: TestClient) -> None:
    provider, instrument, _, _ = asyncio.run(seed())
    later = [
        c.model_copy(update={"provider_id": provider, "instrument_id": instrument})
        for c in walk(Timeframe.H1, HOURS + 1, provider, instrument)[HOURS:]
    ]
    asyncio.run(seed_quarters(provider, instrument, later))  # A newer close, not yet analysed.
    use_model(api, StandInModel(), later[-1].close_time + timedelta(days=30))
    body = {"provider": "binance_usdm", "instrument_id": instrument}
    assert api.post("/api/v1/forecasts/analyse", json=body).status_code == 202
    job = finish(api)
    assert job["state"] == "failed"
    assert "too old for a live forecast" in job["message"]
