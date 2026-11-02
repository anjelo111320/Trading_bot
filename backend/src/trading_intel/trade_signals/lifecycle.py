"""Signal states. History is appended and never rewritten."""

from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from trading_intel.domain.candles import Timeframe
from trading_intel.domain.signals import Side
from trading_intel.domain.signals import SignalState as S

ALLOWED: Final[dict[S, frozenset[S]]] = {
    S.CANDIDATE: frozenset({S.VALIDATED, S.REJECTED}),
    S.VALIDATED: frozenset({S.ACTIVE, S.EXPIRED, S.INVALIDATED}),
    S.ACTIVE: frozenset({S.ENTRY_TRIGGERED, S.EXPIRED, S.INVALIDATED}),
    S.ENTRY_TRIGGERED: frozenset({S.TP1_HIT, S.STOPPED, S.INVALIDATED}),
    S.TP1_HIT: frozenset({S.TP2_HIT, S.STOPPED}),
    S.TP2_HIT: frozenset({S.TP3_HIT, S.STOPPED}),
}
TERMINAL: Final = frozenset({S.TP3_HIT, S.STOPPED, S.INVALIDATED, S.EXPIRED, S.REJECTED})


class InvalidTransitionError(ValueError):
    """A signal tried to move in a way the lifecycle forbids."""


def advance(current: S, target: S) -> S:
    if target not in ALLOWED.get(current, frozenset()):
        raise InvalidTransitionError(f"{current} cannot become {target}")
    return target


def dedupe_key(
    account_id: object,
    instrument_id: int,
    side: Side,
    timeframe: Timeframe,
    entry: Decimal,
    atr: Decimal,
) -> str:
    """Two signals in the same half-ATR bucket are the same trade."""
    step = atr / 2
    bucket = (entry / step).to_integral_value(rounding=ROUND_HALF_UP) if step > 0 else entry
    return f"{account_id}:{instrument_id}:{side.value}:{timeframe.value}:{bucket}"
