"""Run Kronos in its own environment and read back its sampled paths.

Kronos (vendor/Kronos, MIT, arXiv 2508.02739) needs PyTorch, which the backend does not
install, so it runs as a separate process: from a pinned checkout with pinned weights,
offline, and with no secrets in its environment. Its output is checked before use.
"""

import csv
import fcntl
import json
import math
import shutil
import subprocess
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any, Final, Protocol

import numpy as np

from trading_intel.core.errors import AppError, ConfigurationError
from trading_intel.core.settings import REPOSITORY_ROOT
from trading_intel.domain.candles import ClosedCandle
from trading_intel.forecasting.paths import SampledPaths

KRONOS_ROOT: Final = REPOSITORY_ROOT / "vendor" / "Kronos"
SCRIPT: Final = REPOSITORY_ROOT / "backend" / "scripts" / "kronos_forecast.py"
LOCK: Final = REPOSITORY_ROOT / "data" / "kronos.lock"


class ForecastUnavailableError(AppError):
    code = "forecast_unavailable"


@dataclass(frozen=True)
class KronosConfig:
    """Pinned so every forecast can be reproduced. Changing a pin makes a new model version."""

    root: Path = KRONOS_ROOT
    script: Path = SCRIPT
    code_revision: str = "67b630e67f6a18c9e9be918d9b4337c960db1e9a"
    model: str = "NeoQuasar/Kronos-small"
    model_revision: str = "901c26c1332695a2a8f243eb2f37243a37bea320"
    tokenizer: str = "NeoQuasar/Kronos-Tokenizer-base"
    tokenizer_revision: str = "0e0117387f39004a9016484a186a908917e22426"
    paths: int = 30
    horizon: int = 24
    context: int = 400
    seed: int = 7
    threads: int = 4  # Fixed, because the thread count can change floating-point results.
    timeout_seconds: float = 900.0
    lock: Path = LOCK  # One Kronos run at a time across processes: it needs about 1 GB.

    @property
    def python(self) -> Path:
        return self.root / ".venv" / "bin" / "python"


@dataclass(frozen=True)
class ModelForecast:
    paths: SampledPaths
    config: KronosConfig
    context_candles: int


class ForecastModel(Protocol):
    config: KronosConfig

    def forecast(self, candles: Sequence[ClosedCandle]) -> ModelForecast: ...


@contextmanager
def exclusive(path: Path, *, wait: bool = True) -> Iterator[None]:
    """Hold an exclusive lock on a file. Without `wait`, a held lock raises BlockingIOError."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX if wait else fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


class KronosRunner:
    def __init__(self, config: KronosConfig | None = None) -> None:
        self.config = config or KronosConfig()

    def check(self) -> None:
        """Refuse to run anything but the pinned, unmodified checkout."""
        config = self.config
        for needed in (config.python, config.script):
            if not needed.exists():
                raise ConfigurationError(f"Kronos is not installed: {needed} is missing")
        head = _git(config.root, "rev-parse", "HEAD") or "no revision"
        if head != config.code_revision:
            raise ConfigurationError(
                f"vendor/Kronos is at {head}, not the pinned {config.code_revision}"
            )
        if _git(config.root, "status", "--porcelain"):
            raise ConfigurationError("vendor/Kronos has local changes")

    def forecast(self, candles: Sequence[ClosedCandle]) -> ModelForecast:
        """Sample paths after the last candle. Blocks for about two minutes on this computer."""
        config = self.config
        if len(candles) < config.context:
            raise ForecastUnavailableError(
                f"Kronos needs {config.context} candles, got {len(candles)}"
            )
        context = list(candles[-config.context :])
        timeframe = context[-1].timeframe
        if any(timeframe.next_open(a.open_time) != b.open_time for a, b in pairwise(context)):
            raise ForecastUnavailableError("the candles given to Kronos have a gap")
        self.check()
        with exclusive(config.lock), tempfile.TemporaryDirectory(prefix="kronos-") as folder:
            source, target = Path(folder) / "candles.csv", Path(folder) / "forecast.json"
            _write_csv(source, context)
            command = [
                str(config.python),
                str(config.script),
                str(source),
                str(target),
                *("--paths", str(config.paths), "--horizon", str(config.horizon)),
                *("--context", str(config.context), "--seed", str(config.seed)),
                *("--model", config.model, "--model-revision", config.model_revision),
                *("--tokenizer", config.tokenizer),
                *("--tokenizer-revision", config.tokenizer_revision),
                *("--threads", str(config.threads)),
            ]
            try:
                result = subprocess.run(  # noqa: S603 - fixed interpreter and script
                    command,
                    capture_output=True,
                    text=True,
                    timeout=config.timeout_seconds,
                    env=_environment(),
                    cwd=folder,
                    check=False,
                )
            except subprocess.TimeoutExpired as error:
                raise ForecastUnavailableError(
                    f"Kronos took longer than {config.timeout_seconds:.0f} seconds"
                ) from error
            if result.returncode != 0:
                raise ForecastUnavailableError(f"Kronos failed: {result.stderr.strip()[-500:]}")
            try:
                data = json.loads(target.read_text())
            except (OSError, ValueError) as error:
                raise ForecastUnavailableError("Kronos wrote no readable forecast") from error
        return ModelForecast(_parse(data, context, config), config, len(context))


def _environment() -> dict[str, str]:
    """Only what the model needs, so no secret or database setting reaches the process."""
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": str(Path.home()),  # Locates the downloaded weights.
        "HF_HUB_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def _git(root: Path, *args: str) -> str:
    git = shutil.which("git")
    if git is None:
        raise ConfigurationError("git is needed to check the Kronos checkout")
    result = subprocess.run(  # noqa: S603 - fixed arguments
        [git, "-C", str(root), *args], capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _write_csv(path: Path, candles: Sequence[ClosedCandle]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume", "amount"])
        for c in candles:
            opened = c.open_time.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")
            writer.writerow([opened, c.open, c.high, c.low, c.close, c.volume, c.quote_volume])


def _parse(data: Any, context: Sequence[ClosedCandle], config: KronosConfig) -> SampledPaths:
    last = context[-1]
    try:
        echo = tuple(
            data[k] for k in ("model", "model_revision", "tokenizer", "tokenizer_revision", "seed")
        )
        stamps = [datetime.fromisoformat(t).replace(tzinfo=UTC) for t in data["timestamps"]]
        candles = np.array(data["paths"], dtype=np.float64)
        last_close = float(data["last_close"])
    except (KeyError, TypeError, ValueError) as error:
        raise ForecastUnavailableError("Kronos output is not in the expected format") from error
    requested = (
        config.model,
        config.model_revision,
        config.tokenizer,
        config.tokenizer_revision,
        config.seed,
    )
    if echo != requested:
        raise ForecastUnavailableError("Kronos ran a different model or seed than requested")
    if candles.shape != (config.paths, config.horizon, 4):
        raise ForecastUnavailableError(f"Kronos returned paths of shape {candles.shape}")
    expected, opened = [], last.open_time
    for _ in range(config.horizon):
        opened = last.timeframe.next_open(opened)
        expected.append(opened)
    if stamps != expected:
        raise ForecastUnavailableError("Kronos forecast the wrong candle times")
    if not math.isclose(last_close, float(last.close), rel_tol=1e-12):
        raise ForecastUnavailableError("Kronos read a different last close")
    try:
        return SampledPaths(
            source=config.model,
            timeframe=last.timeframe,
            as_of=last.close_time,
            last_close=float(last.close),
            candles=candles,
        )
    except ValueError as error:
        raise ForecastUnavailableError(f"Kronos output is invalid: {error}") from error
