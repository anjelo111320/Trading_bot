"""Anything known at time T must not change when later candles exist."""

import numpy as np
import pytest

from tests.quant_data import random_walk
from trading_intel.technical_analysis.pipeline import compute_indicators

FULL = random_walk(400, seed=3)
FULL_RESULTS = compute_indicators(FULL)


@pytest.mark.parametrize("end", [60, 150, 275, 399])
def test_every_indicator_is_prefix_stable(end: int) -> None:
    partial = compute_indicators(FULL.upto(end))
    for name, values in partial.items():
        np.testing.assert_array_equal(
            values, FULL_RESULTS[name][:end], err_msg=f"{name} changed when later candles existed"
        )
