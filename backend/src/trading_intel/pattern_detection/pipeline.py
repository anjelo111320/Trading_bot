"""Run every detector. The same code runs live and in backtests."""

from collections.abc import Sequence

from trading_intel.domain.patterns import DetectedPattern, Direction
from trading_intel.market_structure.liquidity import equal_levels, liquidity_sweeps
from trading_intel.market_structure.structure import StructureEvent, analyse_structure
from trading_intel.market_structure.swings import Swing, find_swings
from trading_intel.market_structure.zones import consolidations, supply_demand_zones
from trading_intel.pattern_detection.breakouts import breakouts
from trading_intel.pattern_detection.candles import engulfing, pin_bars_and_dojis
from trading_intel.pattern_detection.divergences import divergences
from trading_intel.pattern_detection.imbalance import fair_value_gaps, order_blocks
from trading_intel.technical_analysis.momentum import rsi
from trading_intel.technical_analysis.series import CandleSeries
from trading_intel.technical_analysis.volatility import atr
from trading_intel.technical_analysis.volume import relative_volume


def structure_patterns(
    events: Sequence[StructureEvent], swings: Sequence[Swing]
) -> list[DetectedPattern]:
    """Structure events as patterns, plus reversals once a swing confirms the new direction."""
    found: list[DetectedPattern] = []
    for position, event in enumerate(events):
        found.append(
            DetectedPattern(
                pattern_type="choch" if event.kind == "CHOCH" else "bos",
                direction=event.direction,
                formed_at=event.time,
                detected_at=event.time,
                price_level=event.level,
                strength=50.0,
            )
        )
        if event.kind != "CHOCH":
            continue
        rising = event.direction is Direction.BULLISH
        wanted = "HL" if rising else "LH"
        confirming = next(
            (s for s in swings if s.confirmed_index > event.index and s.label == wanted), None
        )
        if confirming is None:
            continue
        reversal = DetectedPattern(
            pattern_type="trend_reversal",
            direction=event.direction,
            formed_at=event.time,
            detected_at=confirming.confirmed_at,
            price_level=confirming.price,
            strength=60.0,
            evidence={"confirming_swing": confirming.label},
        )
        opposite = next(
            (
                later
                for later in events[position + 1 :]
                if later.kind == "CHOCH" and later.direction is not event.direction
            ),
            None,
        )
        if opposite is not None and opposite.time < confirming.confirmed_at:
            continue  # The move had already reversed before it could be confirmed.
        if opposite is not None:
            reversal = reversal.invalidated(opposite.time)
        found.append(reversal)
    return found


def detect_patterns(series: CandleSeries) -> list[DetectedPattern]:
    swings = find_swings(series)
    structure = analyse_structure(series, swings)
    volatility = atr(series)
    found = [
        *structure_patterns(structure.events, swings),
        *engulfing(series),
        *pin_bars_and_dojis(series),
        *fair_value_gaps(series, volatility),
        *order_blocks(series, structure.events, volatility),
        *breakouts(series, structure.events, relative_volume(series.volume)),
        *divergences(swings, rsi(series.close)),
        *equal_levels(series, swings, volatility),
        *liquidity_sweeps(series, swings),
        *supply_demand_zones(series, volatility),
        *consolidations(series, volatility),
    ]
    return sorted(found, key=lambda p: (p.detected_at, p.pattern_type, p.formed_at))
