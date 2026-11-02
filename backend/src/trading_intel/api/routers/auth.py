from datetime import timedelta
from ipaddress import ip_address
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from trading_intel.api.auth import (
    SESSION_COOKIE,
    TICKET_SECONDS,
    Owner,
    set_session_cookie,
    verify_password,
)
from trading_intel.api.container import Container, get_container
from trading_intel.api.errors import request_id_of
from trading_intel.api.schemas.auth import LoginRequest, OwnerView, TicketView
from trading_intel.core.errors import AuthenticationError

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

Services = Annotated[Container, Depends(get_container)]


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _ip_address(client: str) -> str | None:
    """The audit column holds addresses only, and a client name is not always one."""
    try:
        return str(ip_address(client))
    except ValueError:
        return None


@router.post("/login", response_model=OwnerView)
async def login(
    body: LoginRequest, request: Request, response: Response, services: Services
) -> OwnerView:
    client = _client(request)
    services.limiter.check(client)
    user = await services.users.by_email(body.email)
    if user is None or not verify_password(user.password_hash, body.password):
        await services.audit.record(
            body.email[:254],
            "login_failed",
            "session",
            request_id=request_id_of(request),
            ip_address=_ip_address(client),
        )
        raise AuthenticationError("Email or password is incorrect.")
    lifetime = timedelta(hours=services.settings.session_lifetime_hours)
    token = services.signer.issue(user.id, lifetime, "session")
    set_session_cookie(
        response,
        token,
        secure=services.settings.app_env == "production",
        max_age=int(lifetime.total_seconds()),
    )
    await services.audit.record(
        user.email,
        "login",
        "session",
        request_id=request_id_of(request),
        ip_address=_ip_address(client),
    )
    return OwnerView(email=user.email, role=user.role)


@router.post("/logout", status_code=204)
async def logout(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", response_model=OwnerView)
async def me(owner: Owner) -> OwnerView:
    return OwnerView(email=owner.email, role=owner.role)


@router.post("/ws-ticket", response_model=TicketView)
async def ws_ticket(owner: Owner, services: Services) -> TicketView:
    ticket = services.signer.issue(owner.id, timedelta(seconds=TICKET_SECONDS), "websocket")
    return TicketView(ticket=ticket, expires_in_seconds=TICKET_SECONDS)
