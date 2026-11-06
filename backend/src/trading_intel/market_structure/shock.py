"""Down warnings: the first leg of a fall, pre-registered in docs/32-SHOCK-STUDY.md.

A warning at a candle uses only that candle and earlier ones, so a live run sees the same
warnings a backtest does. Whether a warning is worth acting on is the study's question.
"""

from typing import Final

import numpy as np
import numpy.typing as npt

from trading_intel.technical_analysis.series import CandleSeries

RANGE_CANDLES: Final = 12
VOLUME_CANDLES: Final = 24
VOLUME_MULTIPLE: Final = 2.0
SELLER_SHARE: Final = 0.55


def down_warnings(
    series: CandleSeries,
    *,
    range_candles: int = RANGE_CANDLES,
    volume_candles: int = VOLUME_CANDLES,
    volume_multiple: float = VOLUME_MULTIPLE,
    seller_share: float = SELLER_SHARE,
) -> npt.NDArray[np.bool_]:
    """True at a close below the previous candles' lowest low, on volume at least
    `volume_multiple` times its recent mean, with takers selling at least `seller_share`
    of it. A candle without taker data never warns."""
    flags = np.zeros(len(series), dtype=bool)
    low, close, volume = series.low, series.close, series.volume
    bought = series.taker_buy_volume
    for index in range(max(range_candles, volume_candles), len(series)):
        if close[index] >= low[index - range_candles : index].min():
            continue
        average = volume[index - volume_candles : index].mean()
        if average <= 0 or volume[index] < volume_multiple * average:
            continue
        share_bought = bought[index] / volume[index]
        if share_bought == share_bought and share_bought <= 1 - seller_share:
            flags[index] = True
    return flags
