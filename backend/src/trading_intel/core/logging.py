"""JSON logs with secret filtering."""

import logging
import re
import sys
from collections.abc import Iterable, MutableMapping
from typing import Any

import structlog

REDACTED = "[redacted]"

_SENSITIVE_KEY = re.compile(r"(password|secret|token|api_?key|authorization|cookie)", re.IGNORECASE)


class SecretFilter:
    """Remove configured secrets and sensitive fields from a log event."""

    def __init__(self, secrets: Iterable[str]) -> None:
        self._secrets = tuple(sorted(set(secrets), key=len, reverse=True))

    def __call__(
        self, _logger: object, _method: str, event: MutableMapping[str, Any]
    ) -> MutableMapping[str, Any]:
        for key, value in list(event.items()):
            event[key] = REDACTED if _SENSITIVE_KEY.search(key) else self._clean(value)
        return event

    def _clean(self, value: object) -> object:
        if isinstance(value, str):
            for secret in self._secrets:
                value = value.replace(secret, REDACTED)
            return value
        if isinstance(value, dict):
            return {
                key: REDACTED if _SENSITIVE_KEY.search(str(key)) else self._clean(item)
                for key, item in value.items()
            }
        if isinstance(value, list | tuple):
            return [self._clean(item) for item in value]
        return value


def configure_logging(level: str, secrets: Iterable[str]) -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            SecretFilter(secrets),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=False,
    )
