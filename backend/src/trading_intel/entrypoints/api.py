"""Run the API on the local interface."""

import uvicorn

from trading_intel.api.app import create_app
from trading_intel.core.logging import configure_logging
from trading_intel.core.settings import load_settings


def main() -> None:
    settings = load_settings()
    configure_logging(settings.log_level, settings.secret_values())
    uvicorn.run(create_app(settings), host="127.0.0.1", port=8000, log_config=None)


if __name__ == "__main__":
    main()
