"""One- and two-candle patterns."""

from typing import Final

from trading_intel.domain.patterns import DetectedPattern, Direction, clamp_score
from trading_intel.technical_analysis.series import CandleSeries

PIN_BODY_MAX: Final = 0.25
PIN_WICK_MIN: Final = 0.60
PIN_OTHER_WICK_MAX: Final = 0.20
DOJI_BODY_MAX: Final = 0.10


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
