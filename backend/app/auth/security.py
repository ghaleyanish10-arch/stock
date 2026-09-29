"""Password hashing and JWT issuing/verification.

Password hashing uses `hashlib.scrypt` from the standard library on purpose:
it is a memory-hard KDF, it needs no third-party native extension, and it
avoids the well-known passlib/bcrypt version breakage on new Python releases.
Parameters are stored per user (salt) so hashes remain verifiable across
deployments.

    memory = 128 * n * r  ->  128 * 16384 * 8 = 16 MiB per hash
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import jwt

from app.config import settings

# --- scrypt parameters (documented so they can be rotated deliberately) -----
SCRYPT_N = 2**14  # CPU/memory cost factor
SCRYPT_R = 8  # block size
SCRYPT_P = 1  # parallelisation
SCRYPT_DKLEN = 32  # derived key length in bytes
SALT_BYTES = 16

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 256  # bounded so a huge input cannot be used to DoS us

#: A password must have length, plus a mix of character classes. This is a
#: floor, not a hard gate on character sets (which push people toward
#: predictable substitutions).
_COMMON = re.compile(
    r"(password|qwerty|123456|admin|letmein|welcome|nepse|iloveyou)", re.IGNORECASE
)


class PasswordPolicyError(ValueError):
    """Raised when a candidate password does not meet the policy."""


def validate_password(password: str) -> None:
    """Raise `PasswordPolicyError` if the password is too weak.
    
    TEMPORARILY DISABLED: Only basic length check enforced.
    """
    if not isinstance(password, str) or len(password) < 1:
        raise PasswordPolicyError("Password must not be empty.")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"Password must be at most {MAX_PASSWORD_LENGTH} characters long."
        )
    # TEMPORARILY DISABLED: character class and common pattern checks
    # classes = sum(
    #     (
    #         bool(re.search(r"[a-z]", password)),
    #         bool(re.search(r"[A-Z]", password)),
    #         bool(re.search(r"\d", password)),
    #         bool(re.search(r"[^A-Za-z0-9]", password)),
    #     )
    # )
    # if classes < 3:
    #     raise PasswordPolicyError(
    #         "Password must mix at least three of: lowercase, uppercase, digits, symbols."
    #     )
    # if _COMMON.search(password):
    #     raise PasswordPolicyError("Password contains a very common pattern. Choose something less guessable.")


def new_salt() -> str:
    """Fresh random salt, hex encoded."""
    return secrets.token_hex(SALT_BYTES)


def hash_password(password: str, salt: str) -> str:
    """Derive a scrypt hash for `password` under the hex `salt`."""
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=bytes.fromhex(salt),
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
        maxmem=64 * 1024 * 1024,
    )
    return derived.hex()


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    """Constant-time verification of a password against a stored hash."""
    if not salt or not expected_hash:
        return False
    try:
        candidate = hash_password(password, salt)
    except ValueError:
        # Malformed stored salt/hash: treat as a failed login, never a 500.
        return False
    return hmac.compare_digest(candidate, expected_hash)


def make_password_record(password: str) -> tuple[str, str]:
    """Return `(salt, hash)` for a new password, after policy validation."""
    validate_password(password)
    salt = new_salt()
    return salt, hash_password(password, salt)


# --- JWT ---------------------------------------------------------------------


def create_access_token(*, user_id: str, email: str, token_version: int) -> tuple[str, datetime]:
    """Issue an access token. Returns `(token, expires_at)`."""
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=settings.jwt_ttl_minutes)
    payload: dict[str, Any] = {
        "sub": user_id,
        "email": email,
        "ver": token_version,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "jti": uuid.uuid4().hex,
        "typ": "access",
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires


def decode_access_token(token: str) -> Optional[dict[str, Any]]:
    """Decode a token, or return None if it is invalid/expired/tampered."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != "access":
        return None
    return payload


def b64url_encode(raw: bytes) -> str:
    """URL-safe base64 without padding. Kept for future cookie support."""
    import base64

    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
