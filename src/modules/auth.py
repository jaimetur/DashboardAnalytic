from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field


@dataclass(slots=True)
class SessionUser:
    username: str
    role: str
    session_marker: str = field(default_factory=lambda: secrets.token_urlsafe(12))


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    return f"{salt}${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    # A malformed stored hash can never match; reject it instead of raising.
    salt, separator, expected = str(stored_hash or "").partition("$")
    if not separator:
        return False
    current = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    return hmac.compare_digest(current, expected)
