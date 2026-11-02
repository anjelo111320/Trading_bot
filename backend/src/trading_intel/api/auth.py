"""One owner, one signed session cookie, and short-lived WebSocket tickets (D019).

Everything sits behind `require_owner`, a single dependency that can be replaced.
"""

import base64
import hashlib
import hmac
import json
import secrets
from collections import deque
from datetime import datetime, timedelta
from typing import Annotated
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, Request, Response

from trading_intel.api.container import Container, get_container
from trading_intel.core.clock import Clock, from_epoch_ms, to_epoch_ms
from trading_intel.core.errors import AuthenticationError, RateLimitedError
from trading_intel.database.repositories.accounts import User

SESSION_COOKIE = "ati_session"
LOGIN_ATTEMPTS_PER_MINUTE = 5
TICKET_SECONDS = 30

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(stored_hash, password)
    except VerificationError, InvalidHashError:
        return False


class TokenSigner:
    """Signed, expiring values. The signature uses the application secret."""

    def __init__(self, secret: str, clock: Clock) -> None:
        self._key = hashlib.sha256(secret.encode()).digest()
        self._clock = clock

    def _sign(self, body: bytes) -> str:
        digest = hmac.new(self._key, body, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).decode().rstrip("=")

    def issue(self, user_id: UUID, lifetime: timedelta, purpose: str) -> str:
        claims = {
            "sub": str(user_id),
            "exp": to_epoch_ms(self._clock.now() + lifetime),
            "use": purpose,
            "nonce": secrets.token_urlsafe(8),
        }
        body = base64.urlsafe_b64encode(json.dumps(claims).encode())
        return f"{body.decode().rstrip('=')}.{self._sign(body.rstrip(b'='))}"

    def read(self, token: str, purpose: str) -> tuple[UUID, str] | None:
        """Return the subject and nonce, or None if invalid, expired or for another use."""
        body, _, signature = token.partition(".")
        if not signature or not hmac.compare_digest(self._sign(body.encode()), signature):
            return None
        try:
            padded = body + "=" * (-len(body) % 4)
            claims = json.loads(base64.urlsafe_b64decode(padded))
            expired = from_epoch_ms(claims["exp"]) <= self._clock.now()
            subject = UUID(claims["sub"])
        except ValueError, KeyError, TypeError:
            return None
        if expired or claims.get("use") != purpose:
            return None
        return subject, claims["nonce"]


class LoginLimiter:
    """Counts attempts per client address in a rolling minute."""

    def __init__(self, clock: Clock, limit: int = LOGIN_ATTEMPTS_PER_MINUTE) -> None:
        self._clock = clock
        self._limit = limit
        self._attempts: dict[str, deque[datetime]] = {}

    def check(self, client: str) -> None:
        now = self._clock.now()
        attempts = self._attempts.setdefault(client, deque())
        while attempts and now - attempts[0] >= timedelta(minutes=1):
            attempts.popleft()
        if len(attempts) >= self._limit:
            raise RateLimitedError("Too many login attempts. Try again in a minute.")
        attempts.append(now)


class TicketLedger:
    """Remembers used tickets until they expire, so each works only once."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._used: dict[str, datetime] = {}

    def consume(self, nonce: str) -> bool:
        now = self._clock.now()
        self._used = {key: until for key, until in self._used.items() if until > now}
        if nonce in self._used:
            return False
        self._used[nonce] = now + timedelta(seconds=TICKET_SECONDS * 2)
        return True


def set_session_cookie(response: Response, token: str, secure: bool, max_age: int) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )


async def require_owner(
    request: Request, container: Annotated[Container, Depends(get_container)]
) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    claims = container.signer.read(token, "session") if token else None
    if claims is None:
        raise AuthenticationError("Log in to continue.")
    user = await container.users.by_id(claims[0])
    if user is None:
        raise AuthenticationError("Log in to continue.")
    return user


Owner = Annotated[User, Depends(require_owner)]
