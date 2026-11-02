"""Market data for the dashboard. Closed candles only, and every value states its age."""

from datetime import datetime, timedelta
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Query

from trading_intel.api.auth import Owner
from trading_intel.api.container import Container, get_container
from trading_intel.api.schemas.market import (
    CandlePage,
    CandleView,
    CoverageView,
    FeedStatusView,
    GapList,
    GapView,
    InstrumentView,
    MarketStatusView,
    PriceView,
)
from trading_intel.core.clock import UtcDatetime
from trading_intel.core.errors import NotFoundError
from trading_intel.domain.candles import Timeframe
from trading_intel.domain.events import (
    MARKET_PRICE,
    MARKET_STATUS,
    MarketStatusPayload,
    plain,
)

router = APIRouter(prefix="/api/v1", tags=["market"])

Services = Annotated[Container, Depends(get_container)]

STALE_PRICE_SECONDS: Final = 5.0
MARKET_FEEDS: Final = ("binance_spot", "binance_usdm", "synthetic")


async def _provider_id(services: Container, code: str) -> int:
    try:
        return await services.reference.provider_id(code)
    except NotFoundError as error:
        raise NotFoundError("No such provider.") from error


@router.get("/instruments", response_model=list[InstrumentView])
async def instruments(_: Owner, services: Services) -> list[InstrumentView]:
    views: list[InstrumentView] = []
    for item in await services.reference.provider_instruments():
        rules = await services.rules.current(item.provider_id, item.instrument.id)
        views.append(
            InstrumentView(
                id=item.instrument.id,
                symbol=item.instrument.symbol,
                instrument_type=item.instrument.instrument_type,
                base_asset=item.instrument.base_asset,
                quote_asset=item.instrument.quote_asset,
                provider=item.provider_code,
                provider_symbol=item.provider_symbol,
                is_synthetic=item.provider_code == "synthetic",
                tick_size=plain(rules.tick_size.normalize()) if rules else None,
            )
        )
    return views


@router.get("/market/candles", response_model=CandlePage)
async def candles(
    _: Owner,
    services: Services,
    provider: Annotated[str, Query(min_length=1, max_length=40)],
    instrument_id: Annotated[int, Query(gt=0)],
    timeframe: Timeframe,
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
    before: UtcDatetime | None = None,
) -> CandlePage:
    provider_id = await _provider_id(services, provider)
    rows = await services.candles.page(provider_id, instrument_id, timeframe, limit, before)
    older = rows[0].open_time if len(rows) == limit else None
    return CandlePage(
        provider=provider,
        instrument_id=instrument_id,
        timeframe=timeframe,
        items=[CandleView.of(row) for row in rows],
        next_before=older,
    )


@router.get("/market/price", response_model=PriceView)
async def price(
    _: Owner,
    services: Services,
    provider: Annotated[str, Query(min_length=1, max_length=40)],
    instrument_id: Annotated[int, Query(gt=0)],
) -> PriceView:
    envelope = await services.bus.latest(f"{MARKET_PRICE}:{provider}:{instrument_id}")
    if envelope is None:
        return PriceView(
            provider=provider,
            instrument_id=instrument_id,
            bid=None,
            ask=None,
            received_at=None,
            age_seconds=None,
            stale=True,
            data_origin=None,
        )
    received_at = datetime.fromisoformat(envelope.payload["received_at"])
    age = (services.clock.now() - received_at).total_seconds()
    return PriceView(
        provider=provider,
        instrument_id=instrument_id,
        bid=envelope.payload["bid"],
        ask=envelope.payload["ask"],
        received_at=received_at,
        age_seconds=age,
        stale=age > STALE_PRICE_SECONDS,
        data_origin=envelope.data_origin,
    )


@router.get("/market/status", response_model=MarketStatusView)
async def status(_: Owner, services: Services) -> MarketStatusView:
    feeds: list[FeedStatusView] = []
    for code in MARKET_FEEDS:
        envelope = await services.bus.latest(f"{MARKET_STATUS}:{code}")
        if envelope is None:
            if code == "synthetic":
                continue
            feeds.append(
                FeedStatusView(
                    provider=code,
                    state="DISCONNECTED",
                    reasons=["ingestor is not reporting"],
                    last_event_at=None,
                    lag_seconds=None,
                    open_gaps=0,
                    clock_skew_ms=None,
                )
            )
            continue
        payload = MarketStatusPayload.model_validate(envelope.payload)
        feeds.append(FeedStatusView(**payload.model_dump()))
    return MarketStatusView(usable=all(f.state == "HEALTHY" for f in feeds), feeds=feeds)


@router.get("/market/coverage", response_model=CoverageView)
async def coverage(
    _: Owner,
    services: Services,
    hours: Annotated[int, Query(ge=1, le=168)] = 24,
) -> CoverageView:
    end = services.clock.now()
    report = await services.coverage.report(end - timedelta(hours=hours), end)
    return CoverageView.of(report)


@router.get("/market/gaps", response_model=GapList)
async def gaps(
    _: Owner,
    services: Services,
    provider: Annotated[str | None, Query(max_length=40)] = None,
    instrument_id: Annotated[int | None, Query(gt=0)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> GapList:
    provider_id = await _provider_id(services, provider) if provider else None
    rows = await services.gaps.list(
        provider_id=provider_id, instrument_id=instrument_id, limit=limit
    )
    return GapList(
        items=[
            GapView(
                provider_id=row.provider_id,
                instrument_id=row.instrument_id,
                timeframe=row.timeframe,
                gap_start=row.gap_start,
                gap_end=row.gap_end,
                state=row.state,
                cause=row.cause,
                detected_at=row.detected_at,
                resolved_at=row.resolved_at,
            )
            for row in rows
        ]
    )
