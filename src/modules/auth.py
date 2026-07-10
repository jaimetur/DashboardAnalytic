from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass


@dataclass(slots=True)
class SessionUser:
    username: str
    role: str


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    return f"{salt}${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    salt, expected = stored_hash.split("$", maxsplit=1)
    current = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    return hmac.compare_digest(current, expected)
