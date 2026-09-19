"""Password hashing and opaque tokens. Tokens are stored as SHA-256 hashes only."""

from __future__ import annotations

import hashlib
import secrets
from typing import Tuple

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()

COLLECTOR_TOKEN_PREFIX = "flk_"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    if not password_hash:
        # Spend comparable time so a missing user is not distinguishable by timing.
        _hasher.hash(password)
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_login_token() -> Tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def new_collector_token() -> Tuple[str, str, str]:
    """Returns ``(token, prefix_for_display, hash)``."""
    token = COLLECTOR_TOKEN_PREFIX + secrets.token_urlsafe(30)
    return token, token[:10], hash_token(token)
