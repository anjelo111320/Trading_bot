"""One JSON error structure for every failure."""

from uuid import uuid7

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException

from trading_intel.core.errors import AppError

log = structlog.get_logger(__name__)


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str


class ErrorResponse(BaseModel):
    error: ErrorBody


def request_id_of(request: Request) -> str:
    return getattr(request.state, "request_id", str(uuid7()))


def _respond(request: Request, status: int, code: str, message: str) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorBody(code=code, message=message, request_id=request_id_of(request))
    )
    return JSONResponse(status_code=status, content=body.model_dump())


async def _app_error(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, AppError)
    return _respond(request, error.status_code, error.code, error.message)


async def _http_error(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, HTTPException)
    code = {404: "not_found", 405: "method_not_allowed"}.get(error.status_code, "http_error")
    return _respond(request, error.status_code, code, str(error.detail))


async def _validation_error(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, RequestValidationError)
    problems = "; ".join(
        f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}" for item in error.errors()
    )
    return _respond(request, 422, "invalid_request", problems)


async def _unexpected_error(request: Request, error: Exception) -> JSONResponse:
    log.error("unhandled_error", error_type=type(error).__name__, path=request.url.path)
    return _respond(request, 500, "internal_error", "An unexpected error occurred.")


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(HTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unexpected_error)
