"""Model forecasts beside Python's levels and patterns, for the dashboard (D040).

The view is read-only. Re-analysis runs a new Kronos forecast from the latest stored 1H
close in the background. Nothing here places, sizes or changes a trade.
"""

import asyncio
from collections import OrderedDict
from datetime import datetime
from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from trading_intel.api.auth import Owner
from trading_intel.api.container import Container, get_container
from trading_intel.api.forecast_view import (
    SETUP,
    AnalysisPart,
    ForecastPart,
    MarketInputs,
    analysis_part,
    assemble,
    forecast_part,
    load_manual_plan,
    plan_status,
    plan_view,
    stored_parameters,
)
from trading_intel.api.schemas.forecasts import (
    AnalyseRequest,
    AnalysisJobView,
    ForecastView,
    PlanView,
)
from trading_intel.core.errors import NotFoundError
from trading_intel.database.repositories.reference import ProviderInstrument
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
CACHE_SIZE: Final = 16

# Both parts are fixed once computed: a forecast never changes, and neither do closed candles.
# The analysis also depends on the baseline settings, so the projection matches the forecast.
_forecast_parts: OrderedDict[UUID, ForecastPart] = OrderedDict()
_analysis_parts: OrderedDict[tuple[int, datetime, TimeMachineParameters, int], AnalysisPart] = (
    OrderedDict()
)


def _remember[K, V](cache: OrderedDict[K, V], key: K, value: V) -> V:
    cache[key] = value
    while len(cache) > CACHE_SIZE:
        cache.popitem(last=False)
    return value


async def _instrument(services: Container, provider: str, instrument_id: int) -> ProviderInstrument:
    listed = await services.reference.provider_instruments(provider)
    item = next((i for i in listed if i.instrument.id == instrument_id), None)
    if item is None:
        raise NotFoundError("No such instrument for this provider.")
    return item


@router.get("/forecasts/latest", response_model=ForecastView)
async def latest_forecast(
    _: Owner,
    services: Services,
    provider: Annotated[str, Query(min_length=1, max_length=40)],
    instrument_id: Annotated[int, Query(gt=0)],
) -> ForecastView:
    item = await _instrument(services, provider, instrument_id)
    provider_id, candles = item.provider_id, services.candles
    config = KronosConfig()
    stored = await services.forecasts.latest(
        provider_id, instrument_id, SETUP, config.model, config.model_revision
    )
    rules = await services.rules.current(provider_id, instrument_id)
    latest = await candles.latest_open_time(provider_id, instrument_id, SETUP)
    if stored is None:
        raise NotFoundError("No forecast is stored for this instrument yet.")
    if rules is None or latest is None:
        raise NotFoundError("The candles or rules behind this forecast are not stored.")

    forecast = _forecast_parts.get(stored.id)
    if forecast is None:
        size = max(stored.key.horizon_candles, TimeMachineParameters().lookback) + ATR_PERIOD + 1
        history = await candles.for_analysis(
            provider_id, instrument_id, SETUP, stored.key.as_of, size
        )
        computed = await asyncio.to_thread(
            forecast_part, stored, await services.forecasts.paths(stored.id), history
        )
        forecast = _remember(_forecast_parts, stored.id, computed)

    parameters, horizon = stored_parameters(stored), stored.key.horizon_candles
    analysis_key = (instrument_id, SETUP.close_time(latest), parameters, horizon)
    analysis = _analysis_parts.get(analysis_key)
    if analysis is None:
        as_of = analysis_key[1]
        market = MarketInputs(
            hours=await candles.for_analysis(provider_id, instrument_id, SETUP, as_of, HOURS),
            fours=await candles.for_analysis(
                provider_id, instrument_id, Timeframe.H4, as_of, FOURS
            ),
            days=await candles.for_analysis(provider_id, instrument_id, Timeframe.D1, as_of, DAYS),
            tick=rules.tick_size,
            lot_step=rules.lot_step,
        )
        if not market.hours or not market.fours or not market.days:
            raise NotFoundError("The candles behind this analysis are not stored.")
        analysis = _remember(
            _analysis_parts,
            analysis_key,
            await asyncio.to_thread(analysis_part, market, parameters, horizon),
        )

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

    plan: PlanView | None = None
    manual = await asyncio.to_thread(
        load_manual_plan, services.settings.manual_signals_dir, item.instrument.symbol
    )
    if manual is not None and manual.signal["plan"]["action"] in ("BUY", "SELL"):
        placed = datetime.fromisoformat(manual.signal["created_at"])
        quarters = [
            c
            for c in await candles.range(
                provider_id,
                instrument_id,
                Timeframe.M15,
                Timeframe.M15.floor(placed),
                services.clock.now(),
            )
            if c.data_origin is not DataOrigin.SYNTHETIC
        ]
        status_now = plan_status(manual, quarters, rules.tick_size, rules.lot_step, stored.atr)
        plan = plan_view(manual, status_now)

    return assemble(
        provider=provider,
        symbol=item.instrument.symbol,
        stored=stored,
        forecast=forecast,
        analysis=analysis,
        record=record,
        plan=plan,
    )


def _job_view(services: Container) -> AnalysisJobView:
    job = services.analyses.current
    if job is None:
        return AnalysisJobView(state="idle")
    return AnalysisJobView(
        state=job.state,
        instrument_id=job.instrument_id,
        symbol=job.symbol,
        as_of=job.as_of,
        started_at=job.started_at,
        finished_at=job.finished_at,
        message=job.message,
    )


@router.post(
    "/forecasts/analyse", response_model=AnalysisJobView, status_code=status.HTTP_202_ACCEPTED
)
async def start_analysis(_: Owner, services: Services, body: AnalyseRequest) -> AnalysisJobView:
    """Forecast from the latest stored 1H close. Returns at once; poll the status."""
    item = await _instrument(services, body.provider, body.instrument_id)
    latest = await services.candles.latest_open_time(item.provider_id, item.instrument.id, SETUP)
    if latest is None:
        raise NotFoundError("No 1H candle is stored for this instrument.")
    as_of = SETUP.close_time(latest)
    forecaster = services.forecaster
    key = forecaster.key(item.provider_id, item.instrument.id, SETUP, as_of)

    async def work() -> str | None:
        existing = await services.forecasts.find(key)
        await forecaster.forecast(item.provider_id, item.instrument.id, SETUP, as_of, "manual")
        return (
            "Already analysed at this close, so the stored forecast was kept." if existing else None
        )

    services.analyses.start(item.instrument.id, item.instrument.symbol, as_of, work)
    return _job_view(services)


@router.get("/forecasts/analyse", response_model=AnalysisJobView)
async def analysis_status(_: Owner, services: Services) -> AnalysisJobView:
    return _job_view(services)
