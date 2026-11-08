"""Salted PBKDF2 password hashing and verification."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from .constants import PBKDF2_ITERATIONS


def hash_password(
    password: str,
    *,
    salt: str | None = None,
    iterations: int = PBKDF2_ITERATIONS,
) -> str:
    """Return a versioned, salted PBKDF2-SHA256 password hash."""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        iterations,
    )
    return f"pbkdf2_sha256${iterations}${salt}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    """Check a password without leaking timing information."""
    try:
        algorithm, iterations_text, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt),
            iterations,
        ).hex()
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(actual, expected)
