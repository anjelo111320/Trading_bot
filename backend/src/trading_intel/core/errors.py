"""Application errors. The API layer maps these onto one JSON structure."""


class AppError(Exception):
    """An expected failure with a stable code."""

    code = "internal_error"
    status_code = 500

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ConfigurationError(AppError):
    code = "configuration_error"


class NotFoundError(AppError):
    code = "not_found"
    status_code = 404


class AuthenticationError(AppError):
    code = "not_authenticated"
    status_code = 401


class RateLimitedError(AppError):
    code = "rate_limited"
    status_code = 429


class InvalidRequestError(AppError):
    code = "invalid_request"
    status_code = 400


class ConflictError(AppError):
    """The request clashes with work already in progress."""

    code = "conflict"
    status_code = 409


class ProviderError(AppError):
    """A provider failed in a way that may be retried."""

    code = "provider_error"
    status_code = 502


class ProviderHaltError(ProviderError):
    """A provider refused access. Retrying or changing host is not allowed."""

    code = "provider_halted"
