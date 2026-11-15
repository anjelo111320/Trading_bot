"""The profit lock (D066): at +1.5R beyond the entry fill, the stop moves to +1R."""

from decimal import Decimal

from trading_intel.domain.signals import Side
from trading_intel.risk_management.profit_lock import lock_level, profit_lock

D = Decimal
TICK = D("0.01")


def test_a_long_locks_one_r_once_the_mark_is_one_and_a_half_r_up() -> None:
    # Filled at 100, planned risk 2 a unit: the lock waits for 103, then holds 102.
    assert profit_lock(Side.LONG, D(100), D(2), D("102.99"), D(98), TICK) is None
    assert profit_lock(Side.LONG, D(100), D(2), D(103), D(98), TICK) == D("102.00")
    assert profit_lock(Side.LONG, D(100), D(2), D(110), D(98), TICK) == D("102.00")


def test_the_real_eth_short_would_lock_at_1864_74() -> None:
    """The owner's ETH short of 2026-11-14: planned 1902.65 with its stop at 1940.89, so 1R is
    38.24, and Binance filled it at 1902.98."""
    risk = D("1940.89") - D("1902.65")
    entry = D("1902.98")
    assert profit_lock(Side.SHORT, entry, risk, D("1845.63"), D("1940.89"), TICK) is None
    assert profit_lock(Side.SHORT, entry, risk, D("1845.62"), D("1940.89"), TICK) == D("1864.74")


def test_a_stop_at_the_lock_or_tighter_stays() -> None:
    assert profit_lock(Side.LONG, D(100), D(2), D(104), D("102.00"), TICK) is None
    assert profit_lock(Side.LONG, D(100), D(2), D(104), D("103.50"), TICK) is None
    assert profit_lock(Side.SHORT, D(100), D(2), D(96), D("97.00"), TICK) is None


def test_the_lock_rounds_to_the_tick_that_keeps_a_little_less() -> None:
    assert lock_level(Side.LONG, D("100.05"), D(2), D("0.1")) == D("102.0")
    assert lock_level(Side.SHORT, D("100.05"), D(2), D("0.1")) == D("98.1")


def test_nothing_moves_without_a_risk_a_price_or_a_tick() -> None:
    assert profit_lock(Side.LONG, D(100), D(0), D(110), D(98), TICK) is None
    assert profit_lock(Side.LONG, D(100), D(2), D(0), D(98), TICK) is None
    assert profit_lock(Side.LONG, D(100), D(2), D(110), D(98), D(0)) is None
