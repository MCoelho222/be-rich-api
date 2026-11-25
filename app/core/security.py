"""Password hashing and opaque tokens (specs/auth.md §2, §6)."""

import hashlib
import hmac
import secrets
from functools import cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()  # argon2id with the library defaults

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128


def new_token() -> str:
    """A random, URL-safe token with 256 bits of entropy."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """SHA-256 of a token. Only this is stored; the raw token stays with the client."""
    return hashlib.sha256(token.encode()).hexdigest()


def tokens_match(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


@cache
def _dummy_hash() -> str:
    return _hasher.hash("timing-equalizer")


def burn_password_check(password: str) -> None:
    """Spend the same time as a real check, so unknown emails can't be detected by timing."""
    verify_password(_dummy_hash(), password)


def password_problems(password: str, *, email: str, name: str) -> list[str]:
    """NIST SP 800-63B style rules: length only, plus no reuse of the email or name."""
    problems = []
    if len(password) < MIN_PASSWORD_LENGTH:
        problems.append(f"Must be at least {MIN_PASSWORD_LENGTH} characters")
    if len(password) > MAX_PASSWORD_LENGTH:
        problems.append(f"Must be at most {MAX_PASSWORD_LENGTH} characters")
    lowered = password.strip().lower()
    if lowered and lowered in {email.strip().lower(), name.strip().lower()}:
        problems.append("Must not be your email or your name")
    return problems
