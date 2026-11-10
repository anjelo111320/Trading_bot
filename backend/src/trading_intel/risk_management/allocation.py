"""How much of an account's risk limit a trade may use, set by tested evidence (D045).

A share only lowers risk below the profile's limit, as a grade does in D038. Shares weigh
evidence from backtests; they are not win probabilities.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal
from typing import Final

FULL_SHARE: Final = Decimal(1)
HALF_SHARE: Final = Decimal("0.5")
QUARTER_SHARE: Final = Decimal("0.25")
SHARE_STEP: Final = Decimal("0.0001")
ZERO: Final = Decimal(0)


@dataclass(frozen=True)
class Evidence:
    """A strategy's pooled backtest expectancy in R, as docs/33 reports it."""

    pooled_mean: float
    pooled_interval: tuple[float, float] | None
    new_coins_mean: float | None
    doubled_costs_mean: float | None


def evidence_share(evidence: Evidence | None) -> Decimal:
    """The rule pre-registered in docs/33. A strategy with no multi-coin test gets a quarter."""
    if evidence is None or evidence.pooled_mean <= 0:
        return QUARTER_SHARE
    interval = evidence.pooled_interval
    new, doubled = evidence.new_coins_mean, evidence.doubled_costs_mean
    full = (
        interval is not None
        and interval[0] > 0
        and new is not None
        and new > 0
        and doubled is not None
        and doubled > 0
    )
    return FULL_SHARE if full else HALF_SHARE


def loses_on_coin(interval: tuple[float, float] | None) -> bool:
    """A coin where the strategy lost with 95% confidence is left out of the plan."""
    return interval is not None and interval[1] < 0


@dataclass(frozen=True)
class Claim:
    """What one signal asks for at its evidence share, before any other signal is counted."""

    key: str
    share: Decimal
    risk: Decimal
    notional: Decimal


def split(
    claims: Sequence[Claim], risk_room: Decimal, exposure_room: Decimal, slots: int
) -> dict[str, Decimal]:
    """Final shares for signals that arrive together.

    The strongest evidence is served first. A group with the same share that does not fit
    shares what is left in proportion, so equal evidence gets equal risk. A share never rises
    above its claim. Claims past the free position slots, or with no room left, get no share:
    the risk engine then refuses them with the reason.
    """
    shares: dict[str, Decimal] = {}
    risk_left, size_left, slots_left = max(risk_room, ZERO), max(exposure_room, ZERO), slots
    for level in sorted({claim.share for claim in claims}, reverse=True):
        group = sorted((c for c in claims if c.share == level), key=lambda c: c.key)
        group = group[: max(slots_left, 0)]
        risk = sum((c.risk for c in group), ZERO)
        size = sum((c.notional for c in group), ZERO)
        scale = Decimal(1)
        if risk > 0:
            scale = min(scale, risk_left / risk)
        if size > 0:
            scale = min(scale, size_left / size)
        final = (level * scale).quantize(SHARE_STEP, rounding=ROUND_FLOOR)
        if final <= 0:
            continue
        for claim in group:
            shares[claim.key] = final
        used = final / level
        risk_left -= risk * used
        size_left -= size * used
        slots_left -= len(group)
    return shares
