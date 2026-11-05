"""Make, store and resolve model forecasts, and report the model's track record.

Kronos runs only when asked: at a setup, by hand, or for a study of past data. One run at a
time, because each takes about two minutes of this computer's processor.
"""

import asyncio
from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final

from trading_intel.core.clock import Clock
from trading_intel.database.repositories.candles import CandleRepository
from trading_intel.database.repositories.forecasts import (
    ForecastKey,
    ForecastRepository,
    NewForecast,
    Reason,
    StoredForecast,
)
from trading_intel.domain.base import DataOrigin
from trading_intel.domain.candles import Timeframe
from trading_intel.forecasting.evidence import forecast_facts
from trading_intel.forecasting.kronos import ForecastModel, ForecastUnavailableError
from trading_intel.forecasting.scoring import Score, realized, score
from trading_intel.forecasting.summary import PathSummary, summarise
from trading_intel.forecasting.time_machine import TimeMachineParameters, time_machine
from trading_intel.forecasting.track_record import TrackRecord, track_record
from trading_intel.technical_analysis.series import CandleSeries
from trading_intel.technical_analysis.volatility import atr

ATR_PERIOD: Final = 14
FRESH_CANDLES: Final = 2  # A live forecast must start from one of the last two closes.
LIVE: Final[tuple[Reason, ...]] = ("setup", "manual")


class ForecastService:
    def __init__(
        self,
        candles: CandleRepository,
        forecasts: ForecastRepository,
        model: ForecastModel,
        clock: Clock,
        *,
        holdout_start: datetime,
        baseline: TimeMachineParameters | None = None,
    ) -> None:
        self._candles = candles
        self._forecasts = forecasts
        self._model = model
        self._clock = clock
        self._holdout_start = holdout_start
        self._baseline = baseline or TimeMachineParameters()
        self._lock = asyncio.Lock()

    def key(
        self, provider_id: int, instrument_id: int, timeframe: Timeframe, as_of: datetime
    ) -> ForecastKey:
        config = self._model.config
        return ForecastKey(
            provider_id=provider_id,
            instrument_id=instrument_id,
            timeframe=timeframe,
            as_of=as_of,
            horizon_candles=config.horizon,
            model=config.model,
            model_revision=config.model_revision,
            seed=config.seed,
        )

    async def forecast(
        self,
        provider_id: int,
        instrument_id: int,
        timeframe: Timeframe,
        as_of: datetime,
        reason: Reason,
    ) -> StoredForecast:
        """The forecast from the candle closing at `as_of`, made once and then reused."""
        key = self.key(provider_id, instrument_id, timeframe, as_of)
        existing = await self._forecasts.find(key)
        if existing is not None:
            return existing
        self._check_timing(key, reason)
        config = self._model.config
        needed = max(config.context, self._baseline.lookback) + ATR_PERIOD + 1
        rows = await self._candles.for_analysis(
            provider_id, instrument_id, timeframe, as_of, needed
        )
        if len(rows) < needed or rows[-1].close_time != as_of:
            raise ForecastUnavailableError(f"{needed} closed candles up to {as_of} are not stored")
        series = CandleSeries.of(rows)
        if not series.is_continuous:
            raise ForecastUnavailableError(f"the candles before {as_of} have a gap")
        async with self._lock:
            started = self._clock.monotonic()
            result = await asyncio.to_thread(self._model.forecast, rows)
            runtime_ms = round((self._clock.monotonic() - started) * 1000)
        baseline = time_machine(series, config.horizon, self._baseline)
        return await self._forecasts.store(
            NewForecast(
                key=key,
                tokenizer=config.tokenizer,
                tokenizer_revision=config.tokenizer_revision,
                code_revision=config.code_revision,
                context_candles=result.context_candles,
                reason=reason,
                last_close=rows[-1].close,
                atr=float(atr(series, ATR_PERIOD)[-1]),
                paths=result.paths.candles.tolist(),
                summary=summarise(result.paths).as_json(),
                baseline={
                    "parameters": self._baseline.as_json(),
                    "summary": summarise(baseline).as_json(),
                },
                runtime_ms=runtime_ms,
            )
        )

    def _check_timing(self, key: ForecastKey, reason: Reason) -> None:
        if reason == "study":
            ends = key.as_of + key.timeframe.delta * key.horizon_candles
            if ends >= self._holdout_start:
                raise ForecastUnavailableError(
                    f"a study forecast must resolve before the holdout starts on "
                    f"{self._holdout_start:%Y-%m-%d} (D029)"
                )
        elif self._clock.now() - key.as_of > key.timeframe.delta * FRESH_CANDLES:
            raise ForecastUnavailableError(
                f"the candle closing at {key.as_of} is too old for a live forecast"
            )

    async def resolve_due(self) -> tuple[int, int]:
        """Score every forecast whose horizon has passed. Returns (resolved, still waiting)."""
        resolved = waiting = 0
        now = self._clock.now()
        for forecast in await self._forecasts.unresolved():
            key = forecast.key
            first_open = key.as_of + timedelta(milliseconds=1)
            last_open = first_open + key.timeframe.delta * key.horizon_candles
            if key.timeframe.close_time(last_open - key.timeframe.delta) > now:
                waiting += 1
                continue
            rows = [
                c
                for c in await self._candles.range(
                    key.provider_id, key.instrument_id, key.timeframe, first_open, last_open
                )
                if c.data_origin is not DataOrigin.SYNTHETIC
            ]
            if len(rows) < key.horizon_candles or not CandleSeries.of(rows).is_continuous:
                waiting += 1
                continue
            outcome = realized(CandleSeries.of(rows), key.horizon_candles)
            last_close = float(forecast.last_close)
            await self._forecasts.store_outcome(
                forecast.id,
                (max(c.high for c in rows), min(c.low for c in rows), rows[-1].close),
                score(PathSummary.from_json(forecast.summary), outcome, last_close).as_json(),
                score(
                    PathSummary.from_json(forecast.baseline["summary"]), outcome, last_close
                ).as_json(),
            )
            resolved += 1
        return resolved, waiting

    async def track_record(
        self,
        timeframe: Timeframe,
        reasons: Sequence[Reason] = ("setup", "manual", "study"),
        instrument_id: int | None = None,
    ) -> TrackRecord:
        """Scores of this model version so far, across coins unless one is named."""
        config = self._model.config
        rows = await self._forecasts.resolved(
            model=config.model,
            model_revision=config.model_revision,
            timeframe=timeframe,
            horizon_candles=config.horizon,
            reasons=reasons,
            instrument_id=instrument_id,
        )
        return track_record(
            [(Score.from_json(r.model_score), Score.from_json(r.baseline_score)) for r in rows]
        )

    async def facts(
        self, forecast: StoredForecast, levels: Sequence[tuple[str, Decimal]] = ()
    ) -> dict[str, Any]:
        """The forecast section of Claude's context, with the model's track record so far."""
        key = forecast.key
        return forecast_facts(
            PathSummary.from_json(forecast.summary),
            PathSummary.from_json(forecast.baseline["summary"]),
            model_name=key.model,
            timeframe=key.timeframe,
            as_of=key.as_of,
            last_close=float(forecast.last_close),
            atr=forecast.atr,
            record=await self.track_record(key.timeframe),
            levels=[(level_id, float(price)) for level_id, price in levels],
        )
