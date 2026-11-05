"""The Kronos runner's process contract, against stand-in scripts that write test paths.

Only the live test runs the real model. It is opt-in with --live and needs vendor/Kronos.
"""

import json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from tests.quant_data import candle
from trading_intel.core.errors import ConfigurationError
from trading_intel.domain.candles import ClosedCandle, Timeframe
from trading_intel.forecasting.kronos import (
    ForecastUnavailableError,
    KronosConfig,
    KronosRunner,
)

STAND_IN = """
import argparse, csv, json, os, sys, time
from datetime import datetime
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("candles")
parser.add_argument("output")
for flag in ("--paths", "--horizon", "--context", "--seed", "--threads"):
    parser.add_argument(flag, type=int)
for flag in ("--model", "--model-revision", "--tokenizer", "--tokenizer-revision"):
    parser.add_argument(flag)
args = parser.parse_args()
rows = list(csv.DictReader(open(args.candles)))
Path(__file__).with_name("seen.json").write_text(
    json.dumps({"environment": sorted(os.environ), "rows": len(rows)})
)
MODE
last = datetime.fromisoformat(rows[-1]["timestamp"])
step = last - datetime.fromisoformat(rows[-2]["timestamp"])
close = float(rows[-1]["close"])
paths = [
    [[close, close * (1.01 + i / 100), close * (0.99 - i / 100), close * (1 + (i - 1) / 1000)]
     for _ in range(args.horizon)]
    for i in range(args.paths)
]
json.dump(
    {
        "model": args.model,
        "model_revision": args.model_revision,
        "tokenizer": args.tokenizer,
        "tokenizer_revision": args.tokenizer_revision,
        "seed": args.seed,
        "last_close": close,
        "timestamps": [(last + step * (k + 1)).isoformat() for k in range(args.horizon)],
        "paths": paths,
    },
    open(args.output, "w"),
)
"""


def git(root: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603
        ["git", "-C", str(root), *args],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.fixture
def make_runner(tmp_path: Path) -> Callable[..., KronosRunner]:
    """A pinned stand-in checkout whose interpreter is this test's Python."""
    root = tmp_path / "Kronos"
    (root / ".venv" / "bin").mkdir(parents=True)
    (root / ".venv" / "bin" / "python").symlink_to(sys.executable)
    (root / ".gitignore").write_text(".venv\n")
    git(root.parent, "init", "-q", str(root))
    git(root, "add", ".gitignore")
    git(root, "-c", "user.email=t@local.test", "-c", "user.name=t", "commit", "-qm", "pin")

    def build(mode: str = "", **overrides: object) -> KronosRunner:
        script = tmp_path / "stand_in.py"
        script.write_text(STAND_IN.replace("MODE", mode))
        config = KronosConfig(
            root=root,
            script=script,
            code_revision=git(root, "rev-parse", "HEAD"),
            paths=3,
            horizon=4,
            context=20,
            lock=tmp_path / "kronos.lock",  # Never wait on a real Kronos run.
        )
        return KronosRunner(replace(config, **overrides))  # type: ignore[arg-type]

    return build


def candles(count: int = 30) -> list[ClosedCandle]:
    """A labelled synthetic walk, as stored candles."""
    closes = [100.0 + (i % 7) - (i % 3) for i in range(count)]
    return [candle(i, close, close + 1, close - 1, close) for i, close in enumerate(closes)]


def test_runner_reads_back_paths_after_the_last_candle(
    make_runner: Callable[..., KronosRunner], tmp_path: Path
) -> None:
    given = candles(30)
    forecast = make_runner().forecast(given)
    assert forecast.paths.candles.shape == (3, 4, 4)
    assert forecast.paths.as_of == given[-1].close_time
    assert forecast.paths.last_close == float(given[-1].close)
    assert forecast.paths.timeframe is Timeframe.H1
    assert forecast.context_candles == 20
    seen = json.loads((tmp_path / "seen.json").read_text())
    assert seen["rows"] == 20  # Only the context window is sent.


def test_runner_passes_no_secrets_or_settings_to_the_model(
    make_runner: Callable[..., KronosRunner], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only-not-a-key")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test-only")
    make_runner().forecast(candles())
    environment = set(json.loads((tmp_path / "seen.json").read_text())["environment"])
    assert "ANTHROPIC_API_KEY" not in environment and "DATABASE_URL" not in environment
    assert {"HF_HUB_OFFLINE", "HF_HUB_DISABLE_TELEMETRY"} <= environment
    assert os.environ["ANTHROPIC_API_KEY"] == "test-only-not-a-key"


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("sys.exit('model crashed')", "Kronos failed: model crashed"),
        ("open(args.output, 'w').write('{'); sys.exit(0)", "no readable forecast"),
        ("args.seed = 99", "different model or seed"),
        ("args.paths = 2", "shape"),
        ("rows[-1]['timestamp'] = '2030-01-01 00:00:00'", "wrong candle times"),
        ("rows[-1]['close'] = '1'", "different last close"),
    ],
)
def test_runner_rejects_failed_or_mismatched_output(
    make_runner: Callable[..., KronosRunner], mode: str, message: str
) -> None:
    with pytest.raises(ForecastUnavailableError, match=message):
        make_runner(mode).forecast(candles())


def test_runner_gives_up_after_its_timeout(make_runner: Callable[..., KronosRunner]) -> None:
    with pytest.raises(ForecastUnavailableError, match="longer than"):
        make_runner("time.sleep(10)", timeout_seconds=0.5).forecast(candles())


def test_runner_refuses_gaps_and_short_input(make_runner: Callable[..., KronosRunner]) -> None:
    given = candles(30)
    with pytest.raises(ForecastUnavailableError, match="gap"):
        make_runner().forecast(given[:20] + given[21:])
    with pytest.raises(ForecastUnavailableError, match="needs 20 candles"):
        make_runner().forecast(given[:19])


def test_runner_refuses_an_unpinned_or_modified_checkout(
    make_runner: Callable[..., KronosRunner],
) -> None:
    with pytest.raises(ConfigurationError, match="not the pinned"):
        make_runner(code_revision="0" * 40).forecast(candles())
    runner = make_runner()
    (runner.config.root / "model.py").write_text("changed = True\n")
    with pytest.raises(ConfigurationError, match="local changes"):
        runner.forecast(candles())
    with pytest.raises(ConfigurationError, match="not installed"):
        make_runner(root=runner.config.root / "missing").check()


@pytest.mark.live
def test_real_kronos_is_repeatable_for_the_same_seed() -> None:
    runner = KronosRunner(KronosConfig(paths=2, horizon=3, context=64))
    try:
        runner.check()
    except ConfigurationError as error:
        pytest.skip(str(error))
    given = candles(80)
    first, second = runner.forecast(given), runner.forecast(given)
    assert np.array_equal(first.paths.candles, second.paths.candles)
    assert first.paths.candles.shape == (2, 3, 4)
