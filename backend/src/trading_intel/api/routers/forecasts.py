"""Model forecasts beside Python's levels and patterns, for the dashboard (D040).

Read-only: nothing here runs Kronos, places a trade or changes one.
"""

import asyncio
from datetime import datetime
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Query

from trading_intel.api.auth import Owner
from trading_intel.api.container import Container, get_container
from trading_intel.api.forecast_view import (
    SETUP,
    MarketInputs,
    build_view,
    load_manual_plan,
    plan_status,
    plan_view,
)
from trading_intel.api.schemas.forecasts import ForecastView, PlanView
from trading_intel.core.errors import NotFoundError
from trading_intel.domain.base import DataOrigin
from trading_intel.domain.candles import Timeframe
from trading_intel.forecasting.kronos import KronosConfig
from trading_intel.forecasting.scoring import Score
from trading_intel.forecasting.service import ATR_PERIOD
from trading_intel.forecasting.time_machine import TimeMachineParameters
from trading_intel.forecasting.track_record import track_record

router = APIRouter(prefix="/api/v1", tags=["forecasts"])

Services = Annotated[Container, Depends(get_container)]

HOURS: Final = 1440  # 60 days, as the live snapshot reads them.
FOURS: Final = 1200
DAYS: Final = 3000
REASONS: Final = ("setup", "manual", "study")


@router.get("/forecasts/latest", response_model=ForecastView)
async def latest_forecast(
    _: Owner,
    services: Services,
    provider: Annotated[str, Query(min_length=1, max_length=40)],
    instrument_id: Annotated[int, Query(gt=0)],
) -> ForecastView:
    listed = await services.reference.provider_instruments(provider)
    item = next((i for i in listed if i.instrument.id == instrument_id), None)
    if item is None:
        raise NotFoundError("No such instrument for this provider.")
    config = KronosConfig()
    stored = await services.forecasts.latest(
        item.provider_id, instrument_id, SETUP, config.model, config.model_revision
    )
    if stored is None:
        raise NotFoundError("No forecast is stored for this instrument yet.")
    as_of, candles = stored.key.as_of, services.candles
    baseline_candles = (
        max(stored.key.horizon_candles, TimeMachineParameters().lookback) + ATR_PERIOD + 1
    )
    hours = await candles.for_analysis(item.provider_id, instrument_id, SETUP, as_of, HOURS)
    fours = await candles.for_analysis(item.provider_id, instrument_id, Timeframe.H4, as_of, FOURS)
    days = await candles.for_analysis(item.provider_id, instrument_id, Timeframe.D1, as_of, DAYS)
    history = await candles.for_analysis(
        item.provider_id, instrument_id, SETUP, as_of, baseline_candles
    )
    rules = await services.rules.current(item.provider_id, instrument_id)
    if rules is None or not hours or not fours or not days:
        raise NotFoundError("The candles or rules behind this forecast are not stored.")
    market = MarketInputs(hours, fours, days, history, rules.tick_size, rules.lot_step)
    rows = await services.forecasts.resolved(
        model=config.model,
        model_revision=config.model_revision,
        timeframe=SETUP,
        horizon_candles=stored.key.horizon_candles,
        reasons=REASONS,
    )
    record = track_record(
        [(Score.from_json(r.model_score), Score.from_json(r.baseline_score)) for r in rows]
    )
    paths = await services.forecasts.paths(stored.id)

    plan: PlanView | None = None
    manual = await asyncio.to_thread(
        load_manual_plan, services.settings.manual_signals_dir, item.instrument.symbol
    )
    if manual is not None and manual.signal["plan"]["action"] in ("BUY", "SELL"):
        placed = datetime.fromisoformat(manual.signal["created_at"])
        quarters = [
            c
            for c in await candles.range(
                item.provider_id,
                instrument_id,
                Timeframe.M15,
                Timeframe.M15.floor(placed),
                services.clock.now(),
            )
            if c.data_origin is not DataOrigin.SYNTHETIC
        ]
        plan = plan_view(manual, plan_status(manual, quarters, market, stored.atr))

    return await asyncio.to_thread(
        build_view,
        provider=provider,
        symbol=item.instrument.symbol,
        stored=stored,
        paths=paths,
        market=market,
        record=record,
        plan=plan,
    )
