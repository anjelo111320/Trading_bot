"""The crash warning study's own calculations, on synthetic candles and trades."""

from datetime import timedelta
from decimal import Decimal as D
from types import SimpleNamespace
from typing import Any

import numpy as np

from tests.quant_data import START, candle
from trading_intel.domain.candles import Timeframe
from trading_intel.domain.signals import Side
from trading_intel.entrypoints.shock_study import large_falls_ahead, split_trades
from trading_intel.technical_analysis.series import CandleSeries


def test_a_fall_of_six_atr_within_six_candles_is_labelled() -> None:
    rows = [candle(i, 100, 100.5, 99.5, 100, 10, Timeframe.H1) for i in range(20)]
    rows[7] = candle(7, 100, 100.2, 93.9, 94.5, 10, Timeframe.H1)
    flags = large_falls_ahead(CandleSeries.of(rows), np.ones(len(rows)))
    # Closes 1 to 6 have candle 7 among their next six. Close 0 does not.
    assert list(flags[:8]) == [False, True, True, True, True, True, True, False]
    assert not flags[-6:].any(), "the last six closes have no full future"


def trade(hours: float, side: Side, pnl: str) -> Any:
    return SimpleNamespace(
        signal_time=START + timedelta(hours=hours),
        order=SimpleNamespace(side=side),
        result=SimpleNamespace(net_pnl=D(pnl)),
        planned_risk=D(100),
    )


def test_only_longs_within_12_hours_after_a_warning_are_skipped() -> None:
    trades = [
        trade(1, Side.LONG, "-50"),  # Skipped: a long one hour after the warning.
        trade(13, Side.LONG, "200"),  # Too late to be skipped.
        trade(2, Side.SHORT, "100"),  # Shorts are never skipped.
        trade(-1, Side.LONG, "100"),  # Before the warning.
    ]
    skipped, kept = split_trades(trades, [START])
    assert skipped == [-0.5]
    assert kept == [2.0, 1.0, 1.0]
