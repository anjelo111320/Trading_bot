"""Helpers for tests against the Compose PostgreSQL and Redis."""

import os
import subprocess
from pathlib import Path

from tests.conftest import make_settings

BACKEND = Path(__file__).resolve().parents[2]
SUPERUSER_URL = "postgresql://ati_superuser:local_dev_only@127.0.0.1:55432/trading_test"


def alembic(*args: str) -> subprocess.CompletedProcess[str]:
    url = make_settings().migration_database_url.get_secret_value()
    return subprocess.run(  # noqa: S603
        ["uv", "run", "alembic", *args],  # noqa: S607
        capture_output=True,
        text=True,
        cwd=BACKEND,
        check=False,
        env={**os.environ, "MIGRATION_DATABASE_URL": url},
    )
