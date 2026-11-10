"""The money plan (D045): every Python strategy on every core coin, in one paper account.

Signals that arrive at the same close share the account's room. The strongest evidence is
served first, and each strategy's share comes from the six-coin replication study (docs/33).
"""

from datetime import datetime
from decimal import Decimal
from typing import Final

from trading_intel.domain.candles import Timeframe
from trading_intel.risk_management.allocation import FULL_SHARE, HALF_SHARE, QUARTER_SHARE
from trading_intel.risk_management.models import RiskProfile
from trading_intel.trade_signals.baseline import STRATEGY_NAME as BASELINE_NAME
from trading_intel.trade_signals.fvg_choch_strategy import STRATEGY_NAME as FVG_NAME
from trading_intel.trade_signals.pattern_strategy import STRATEGY_NAME as PATTERN_NAME
from trading_intel.trade_signals.trend_strategy import STRATEGY_NAME as TREND_NAME

# 1% risk per trade, at most 3% at risk across open trades, the same as the daily loss limit,
# and no new trades after the account is 3% up in a UTC day. Exposure stays within equity.
PLAN_PROFILE: Final = RiskProfile(
    max_open_positions=10,
    max_open_risk_fraction=Decimal("0.03"),
    daily_profit_stop_fraction=Decimal("0.03"),
)

# Set once by the study's pre-registered rule, run on 2026-11-09 (docs/33). The 4H gap and 15M
# CHoCH strategy took its share by the same rule in its own study, run on 2026-11-10 (docs/35).
EVIDENCE_SHARES: Final[dict[str, Decimal]] = {
    TREND_NAME: FULL_SHARE,
    PATTERN_NAME: HALF_SHARE,
    BASELINE_NAME: QUARTER_SHARE,
    FVG_NAME: HALF_SHARE,
}
# Strategy and coin pairs that lost with 95% confidence in the study. None did.
LEFT_OUT: Final[frozenset[tuple[str, str]]] = frozenset()

# The plan decides at each 15M close, and adds the slower strategies at their own closes.
PLAN_TIMEFRAMES: Final = (Timeframe.M15, Timeframe.H1, Timeframe.D1)


def due(close_time: datetime) -> tuple[Timeframe, ...]:
    """The timeframes whose candle closes at this moment."""
    return tuple(
        timeframe
        for timeframe in PLAN_TIMEFRAMES
        if timeframe.close_time(timeframe.floor(close_time)) == close_time
    )


def share_of(strategy: str) -> Decimal:
    """A strategy the study did not cover gets the smallest share."""
    return EVIDENCE_SHARES.get(strategy, QUARTER_SHARE)
