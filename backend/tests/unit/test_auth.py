from datetime import UTC, datetime, timedelta
from uuid import uuid7

import pytest

from trading_intel.api.auth import (
    LoginLimiter,
    TicketLedger,
    TokenSigner,
    hash_password,
    verify_password,
)
from trading_intel.core.clock import FixedClock
from trading_intel.core.errors import RateLimitedError

NOW = datetime(2026, 1, 1, tzinfo=UTC)
SECRET = "unit-test-secret-value-long-enough-0000000"


def test_password_is_hashed_and_verifies() -> None:
    stored = hash_password("correct horse")
    assert "correct horse" not in stored
    assert stored.startswith("$argon2")
    assert verify_password(stored, "correct horse")
    assert not verify_password(stored, "wrong")


def test_malformed_stored_hash_fails_safely() -> None:
    assert not verify_password("not-a-hash", "anything")


def test_token_round_trips() -> None:
    signer = TokenSigner(SECRET, FixedClock(NOW))
    user = uuid7()
    claims = signer.read(signer.issue(user, timedelta(hours=1), "session"), "session")
    assert claims is not None
    assert claims[0] == user


def test_expired_token_is_refused() -> None:
    clock = FixedClock(NOW)
    signer = TokenSigner(SECRET, clock)
    token = signer.issue(uuid7(), timedelta(hours=1), "session")
    clock.advance(3599)
    assert signer.read(token, "session") is not None
    clock.advance(1)
    assert signer.read(token, "session") is None


def test_tampered_token_is_refused() -> None:
    signer = TokenSigner(SECRET, FixedClock(NOW))
    token = signer.issue(uuid7(), timedelta(hours=1), "session")
    body, _, signature = token.partition(".")
    assert signer.read(f"{body}x.{signature}", "session") is None
    assert signer.read(f"{body}.{signature[:-2]}zz", "session") is None
    assert signer.read("garbage", "session") is None
    assert signer.read("", "session") is None


def test_token_signed_with_another_secret_is_refused() -> None:
    clock = FixedClock(NOW)
    token = TokenSigner("other-secret-value-long-enough-0000000000", clock).issue(
        uuid7(), timedelta(hours=1), "session"
    )
    assert TokenSigner(SECRET, clock).read(token, "session") is None


def test_a_token_for_one_purpose_cannot_be_used_for_another() -> None:
    signer = TokenSigner(SECRET, FixedClock(NOW))
    ticket = signer.issue(uuid7(), timedelta(seconds=30), "websocket")
    assert signer.read(ticket, "session") is None


def test_login_limiter_blocks_the_sixth_attempt_then_recovers() -> None:
    clock = FixedClock(NOW)
    limiter = LoginLimiter(clock)
    for _ in range(5):
        limiter.check("1.2.3.4")
    with pytest.raises(RateLimitedError):
        limiter.check("1.2.3.4")
    limiter.check("5.6.7.8")
    clock.advance(60)
    limiter.check("1.2.3.4")


def test_a_ticket_works_only_once() -> None:
    ledger = TicketLedger(FixedClock(NOW))
    assert ledger.consume("n1")
    assert not ledger.consume("n1")
    assert ledger.consume("n2")
