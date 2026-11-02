"""Write the OpenAPI document, which the frontend's types are generated from."""

import json
from pathlib import Path

from pydantic import SecretStr

from trading_intel.api.app import create_app
from trading_intel.core.settings import REPOSITORY_ROOT, Settings

OPENAPI_PATH: Path = REPOSITORY_ROOT / "backend" / "openapi.json"


def render_openapi() -> str:
    placeholder = SecretStr("not-a-real-value-only-used-to-build-the-schema")
    settings = Settings(
        app_secret_key=placeholder,
        database_url=placeholder,
        ingest_database_url=placeholder,
        migration_database_url=placeholder,
        redis_url=placeholder,
        _env_file=None,
    )
    return json.dumps(create_app(settings).openapi(), indent=2, sort_keys=True) + "\n"


def main() -> None:
    OPENAPI_PATH.write_text(render_openapi())


if __name__ == "__main__":
    main()
