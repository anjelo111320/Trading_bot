"""Candlestick patterns.

Engulfing, pin bars and dojis ignore context. The rest need the right prior trend, because
the same shape means different things after a rise and after a fall (a hammer and a hanging
man). Crypto candles open at the previous close, so no rule needs a gap. Rules are in
docs/25-PATTERN-RULES.md.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal

from trading_intel.domain.patterns import DetectedPattern, Direction, clamp_score
from trading_intel.technical_analysis.series import CandleSeries, FloatArray

PIN_BODY_MAX: Final = 0.25
PIN_WICK_MIN: Final = 0.60
PIN_OTHER_WICK_MAX: Final = 0.20
DOJI_BODY_MAX: Final = 0.10

TREND_LOOKBACK: Final = 10
TREND_MIN_ATR: Final = 1.0
BODY_AVERAGE: Final = 10
LONG_WICK: Final = 0.6
SHORT_WICK: Final = 0.1
MARUBOZU_BODY: Final = 0.9
HARAMI_BODY: Final = 0.5
OPEN_SLACK: Final = 0.1  # Share of the first body. Opens differ from closes by a tick.
TWEEZER_ATR: Final = 0.1
STAR_BODY: Final = 0.3
STAR_SLACK: Final = 0.25
SOLDIER_BODY: Final = 0.5
SOLDIER_WICK: Final = 0.2

PriorTrend = Literal["up", "down", "none"]


def engulfing(series: CandleSeries) -> list[DetectedPattern]:
    found: list[DetectedPattern] = []
    for index in range(1, len(series)):
        previous_open = float(series.open[index - 1])
        previous_close = float(series.close[index - 1])
        current_open = float(series.open[index])
        current_close = float(series.close[index])
        previous_body = abs(previous_close - previous_open)
        current_body = abs(current_close - current_open)
        bullish = (
            previous_close < previous_open
            and current_close > current_open
            and current_open <= previous_close
            and current_close >= previous_open
        )
        bearish = (
            previous_close > previous_open
            and current_close < current_open
            and current_open >= previous_close
            and current_close <= previous_open
        )
        if not (bullish or bearish) or current_body <= previous_body:
            continue
        found.append(
            DetectedPattern(
                pattern_type="bullish_engulfing" if bullish else "bearish_engulfing",
                direction=Direction.BULLISH if bullish else Direction.BEARISH,
                formed_at=series.close_time[index],
                detected_at=series.close_time[index],
                price_level=current_close,
                strength=clamp_score(current_body / previous_body * 25 if previous_body else 100),
                evidence={"previous_body": previous_body, "body": current_body},
            )
        )
    return found


def pin_bars_and_dojis(series: CandleSeries) -> list[DetectedPattern]:
    found: list[DetectedPattern] = []
    for index in range(len(series)):
        high = float(series.high[index])
        low = float(series.low[index])
        open_ = float(series.open[index])
        close = float(series.close[index])
        span = high - low
        if span <= 0:
            continue
        body = abs(close - open_) / span
        upper = (high - max(open_, close)) / span
        lower = (min(open_, close) - low) / span
        when = series.close_time[index]
        if body <= DOJI_BODY_MAX:
            found.append(
                DetectedPattern(
                    "doji",
                    Direction.NEUTRAL,
                    when,
                    when,
                    price_level=close,
                    strength=clamp_score((1 - body / DOJI_BODY_MAX) * 100),
                    evidence={"body_share": round(body, 4)},
                )
            )
        if body <= PIN_BODY_MAX:
            if lower >= PIN_WICK_MIN and upper <= PIN_OTHER_WICK_MAX:
                direction, wick = Direction.BULLISH, lower
            elif upper >= PIN_WICK_MIN and lower <= PIN_OTHER_WICK_MAX:
                direction, wick = Direction.BEARISH, upper
            else:
                continue
            found.append(
                DetectedPattern(
                    "pin_bar",
                    direction,
                    when,
                    when,
                    price_level=low if direction is Direction.BULLISH else high,
                    strength=clamp_score(wick * 100),
                    evidence={"body_share": round(body, 4), "wick_share": round(wick, 4)},
                )
            )
    return found


@dataclass(frozen=True)
class _Shape:
    open: float
    high: float
    low: float
    close: float

    @property
    def span(self) -> float:
        return self.high - self.low

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def upper(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower(self) -> float:
        return min(self.open, self.close) - self.low

    @property
    def bullish(self) -> bool:
        return self.close > self.open

    @property
    def bearish(self) -> bool:
        return self.close < self.open

    @property
    def middle(self) -> float:
        return (self.open + self.close) / 2

    def body_inside(self, other: _Shape) -> bool:
        return max(self.open, self.close) <= max(other.open, other.close) and min(
            self.open, self.close
        ) >= min(other.open, other.close)


def _shape(series: CandleSeries, index: int) -> _Shape:
    return _Shape(
        float(series.open[index]),
        float(series.high[index]),
        float(series.low[index]),
        float(series.close[index]),
    )


def prior_trend(series: CandleSeries, atr: FloatArray, index: int) -> PriorTrend:
    """The move into a pattern starting at `index`: the last 10 closes before it, in ATR."""
    before = index - 1
    if before - TREND_LOOKBACK < 0:
        return "none"
    unit = float(atr[before])
    if unit != unit or unit <= 0:
        return "none"
    move = (float(series.close[before]) - float(series.close[before - TREND_LOOKBACK])) / unit
    if move >= TREND_MIN_ATR:
        return "up"
    if move <= -TREND_MIN_ATR:
        return "down"
    return "none"


def _average_body(series: CandleSeries, index: int) -> float:
    """Mean body of the 10 candles before `index`, like TA-Lib's BodyLong. NaN if too early."""
    if index < BODY_AVERAGE:
        return float("nan")
    window = slice(index - BODY_AVERAGE, index)
    return float(abs(series.close[window] - series.open[window]).mean())


Emit = Callable[..., None]


def _collector(
    found: list[DetectedPattern], formed: datetime, detected: datetime, trend: PriorTrend
) -> Emit:
    def emit(
        pattern_type: str, direction: Direction, level: float, strength: float, **evidence: float
    ) -> None:
        found.append(
            DetectedPattern(
                pattern_type,
                direction,
                formed,
                detected,
                price_level=level,
                strength=clamp_score(strength),
                evidence={"prior_trend": trend, **{k: round(v, 4) for k, v in evidence.items()}},
            )
        )

    return emit


def single_candle_patterns(series: CandleSeries, atr: FloatArray) -> list[DetectedPattern]:
    """Hammer and hanging man, inverted hammer and shooting star, doji variants, marubozu."""
    found: list[DetectedPattern] = []
    for index in range(len(series)):
        c = _shape(series, index)
        if c.span <= 0:
            continue
        trend = prior_trend(series, atr, index)
        when = series.close_time[index]
        emit = _collector(found, when, when, trend)
        upper, lower, body = c.upper / c.span, c.lower / c.span, c.body / c.span
        if c.lower >= 2 * c.body and lower >= LONG_WICK and upper <= SHORT_WICK:
            if trend == "down":
                emit("hammer", Direction.BULLISH, c.low, lower * 100, wick_share=lower)
            elif trend == "up":
                emit("hanging_man", Direction.BEARISH, c.high, lower * 100, wick_share=lower)
        if c.upper >= 2 * c.body and upper >= LONG_WICK and lower <= SHORT_WICK:
            if trend == "down":
                emit("inverted_hammer", Direction.BULLISH, c.low, upper * 100, wick_share=upper)
            elif trend == "up":
                emit("shooting_star", Direction.BEARISH, c.high, upper * 100, wick_share=upper)
        if body <= DOJI_BODY_MAX:
            if upper <= SHORT_WICK and trend == "down":
                emit("dragonfly_doji", Direction.BULLISH, c.low, lower * 100, wick_share=lower)
            elif lower <= SHORT_WICK and trend == "up":
                emit("gravestone_doji", Direction.BEARISH, c.high, upper * 100, wick_share=upper)
        average = _average_body(series, index)
        if body >= MARUBOZU_BODY and average == average and c.body >= average:
            if c.bullish:
                emit("bullish_marubozu", Direction.BULLISH, c.low, body * 100, body_share=body)
            else:
                emit("bearish_marubozu", Direction.BEARISH, c.high, body * 100, body_share=body)
    return found


def two_candle_patterns(series: CandleSeries, atr: FloatArray) -> list[DetectedPattern]:
    """Harami, piercing line and dark cloud cover, tweezers, inside bar."""
    found: list[DetectedPattern] = []
    for index in range(1, len(series)):
        a, b = _shape(series, index - 1), _shape(series, index)
        if a.span <= 0 or b.span <= 0:
            continue
        trend = prior_trend(series, atr, index - 1)
        emit = _collector(found, series.close_time[index - 1], series.close_time[index], trend)
        average = _average_body(series, index - 1)
        long_first = average == average and a.body >= average and a.body > 0
        low, high = min(a.low, b.low), max(a.high, b.high)
        if long_first and 0 < b.body <= HARAMI_BODY * a.body and b.body_inside(a):
            shrink = (1 - b.body / a.body) * 100
            if trend == "down" and a.bearish and b.bullish:
                emit("bullish_harami", Direction.BULLISH, low, shrink, body_ratio=b.body / a.body)
            elif trend == "up" and a.bullish and b.bearish:
                emit("bearish_harami", Direction.BEARISH, high, shrink, body_ratio=b.body / a.body)
        slack = OPEN_SLACK * a.body
        piercing = b.open <= a.close + slack and a.middle < b.close < a.open
        if long_first and trend == "down" and a.bearish and b.bullish and piercing:
            depth = (b.close - a.close) / a.body
            emit("piercing_line", Direction.BULLISH, low, depth * 100, penetration=depth)
        clouding = b.open >= a.close - slack and a.open < b.close < a.middle
        if long_first and trend == "up" and a.bullish and b.bearish and clouding:
            depth = (a.close - b.close) / a.body
            emit("dark_cloud_cover", Direction.BEARISH, high, depth * 100, penetration=depth)
        unit = float(atr[index])
        if unit == unit and unit > 0:
            tolerance = TWEEZER_ATR * unit
            if trend == "down" and a.bearish and b.bullish and abs(a.low - b.low) <= tolerance:
                gap = abs(a.low - b.low) / tolerance
                emit("tweezer_bottom", Direction.BULLISH, low, (1 - gap) * 100, difference=gap)
            if trend == "up" and a.bullish and b.bearish and abs(a.high - b.high) <= tolerance:
                gap = abs(a.high - b.high) / tolerance
                emit("tweezer_top", Direction.BEARISH, high, (1 - gap) * 100, difference=gap)
        if b.high < a.high and b.low > a.low:
            ratio = b.span / a.span
            emit("inside_bar", Direction.NEUTRAL, b.close, (1 - ratio) * 100, range_ratio=ratio)
    return found


def _steps_up(first: _Shape, second: _Shape) -> bool:
    """Second opens within the first body, allowing a tick of slack, and closes higher."""
    slack = OPEN_SLACK * first.body
    return first.open <= second.open <= first.close + slack and second.close > first.close


def _steps_down(first: _Shape, second: _Shape) -> bool:
    slack = OPEN_SLACK * first.body
    return first.close - slack <= second.open <= first.open and second.close < first.close


def three_candle_patterns(series: CandleSeries, atr: FloatArray) -> list[DetectedPattern]:
    """Morning and evening star, three soldiers and crows, three inside and outside."""
    found: list[DetectedPattern] = []
    for index in range(2, len(series)):
        a, b, c = (_shape(series, i) for i in range(index - 2, index + 1))
        if min(a.span, b.span, c.span) <= 0:
            continue
        trend = prior_trend(series, atr, index - 2)
        emit = _collector(found, series.close_time[index - 2], series.close_time[index], trend)
        average = _average_body(series, index - 2)
        long_first = average == average and a.body >= average and a.body > 0
        low, high = min(a.low, b.low, c.low), max(a.high, b.high, c.high)
        star = long_first and b.body <= STAR_BODY * a.body
        doji = 1.0 if b.body <= DOJI_BODY_MAX * b.span else 0.0
        low_star = max(b.open, b.close) <= a.close + STAR_SLACK * a.body
        if star and low_star and trend == "down" and a.bearish and c.bullish and c.close > a.middle:
            depth = (c.close - a.close) / a.body
            emit("morning_star", Direction.BULLISH, low, depth * 100, doji_star=doji)
        high_star = min(b.open, b.close) >= a.close - STAR_SLACK * a.body
        if star and high_star and trend == "up" and a.bullish and c.bearish and c.close < a.middle:
            depth = (a.close - c.close) / a.body
            emit("evening_star", Direction.BEARISH, high, depth * 100, doji_star=doji)
        candles = (a, b, c)
        solid = sum(x.body / x.span for x in candles) / 3 * 100
        soldiers = all(
            x.bullish and x.body >= SOLDIER_BODY * x.span and x.upper <= SOLDIER_WICK * x.span
            for x in candles
        )
        if long_first and trend != "up" and soldiers and _steps_up(a, b) and _steps_up(b, c):
            emit("three_white_soldiers", Direction.BULLISH, a.low, solid, body_share=solid / 100)
        crows = all(
            x.bearish and x.body >= SOLDIER_BODY * x.span and x.lower <= SOLDIER_WICK * x.span
            for x in candles
        )
        if long_first and trend != "down" and crows and _steps_down(a, b) and _steps_down(b, c):
            emit("three_black_crows", Direction.BEARISH, a.high, solid, body_share=solid / 100)
        harami = long_first and 0 < b.body <= HARAMI_BODY * a.body and b.body_inside(a)
        if (
            harami
            and trend == "down"
            and a.bearish
            and b.bullish
            and c.bullish
            and c.close > a.open
        ):
            emit("three_inside_up", Direction.BULLISH, low, 60.0)
        if harami and trend == "up" and a.bullish and b.bearish and c.bearish and c.close < a.open:
            emit("three_inside_down", Direction.BEARISH, high, 60.0)
        slack = OPEN_SLACK * a.body
        engulfs = b.body > a.body > 0
        engulf_up = b.open <= a.close + slack and b.close >= a.open and c.close > b.close
        if trend == "down" and engulfs and engulf_up and a.bearish and b.bullish and c.bullish:
            emit("three_outside_up", Direction.BULLISH, low, b.body / a.body * 25)
        engulf_down = b.open >= a.close - slack and b.close <= a.open and c.close < b.close
        if trend == "up" and engulfs and engulf_down and a.bullish and b.bearish and c.bearish:
            emit("three_outside_down", Direction.BEARISH, high, b.body / a.body * 25)
    return found


def trend_candle_patterns(series: CandleSeries, atr: FloatArray) -> list[DetectedPattern]:
    return [
        *single_candle_patterns(series, atr),
        *two_candle_patterns(series, atr),
        *three_candle_patterns(series, atr),
    ]
