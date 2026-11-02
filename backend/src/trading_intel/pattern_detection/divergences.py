"""Price against RSI at consecutive confirmed swings."""

from collections.abc import Sequence
from itertools import pairwise

import numpy as np

from trading_intel.domain.patterns import DetectedPattern, Direction, clamp_score
from trading_intel.market_structure.swings import Swing
from trading_intel.technical_analysis.series import FloatArray


def divergences(swings: Sequence[Swing], rsi: FloatArray) -> list[DetectedPattern]:
    found: list[DetectedPattern] = []
    for kind in ("high", "low"):
        same = [s for s in swings if s.kind == kind]
        for position, (first, second) in enumerate(pairwise(same)):
            first_rsi, second_rsi = float(rsi[first.index]), float(rsi[second.index])
            if np.isnan(first_rsi) or np.isnan(second_rsi):
                continue
            label = _classify(kind, first.price, second.price, first_rsi, second_rsi)
            if label is None:
                continue
            name, direction = label
            pattern = DetectedPattern(
                pattern_type=name,
                direction=direction,
                formed_at=second.time,
                detected_at=second.confirmed_at,
                price_level=second.price,
                strength=clamp_score(abs(second_rsi - first_rsi) * 5),
                evidence={"rsi_first": round(first_rsi, 3), "rsi_second": round(second_rsi, 3)},
            )
            for later in same[position + 2 :]:
                beyond = (
                    later.price > second.price if kind == "high" else later.price < second.price
                )
                if beyond:
                    pattern = pattern.invalidated(later.confirmed_at)
                    break
            found.append(pattern)
    return found


def _classify(
    kind: str, price_1: float, price_2: float, rsi_1: float, rsi_2: float
) -> tuple[str, Direction] | None:
    if kind == "high":
        if price_2 > price_1 and rsi_2 < rsi_1:
            return "regular_divergence", Direction.BEARISH
        if price_2 < price_1 and rsi_2 > rsi_1:
            return "hidden_divergence", Direction.BEARISH
        return None
    if price_2 < price_1 and rsi_2 > rsi_1:
        return "regular_divergence", Direction.BULLISH
    if price_2 > price_1 and rsi_2 < rsi_1:
        return "hidden_divergence", Direction.BULLISH
    return None
