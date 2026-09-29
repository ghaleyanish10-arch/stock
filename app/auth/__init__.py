"""Authentication: scrypt password hashing, JWT sessions, route dependencies."""

from app.auth.security import (
    PasswordPolicyError,
    create_access_token,
    decode_access_token,
    hash_password,
    make_password_record,
    new_salt,
    validate_password,
    verify_password,
)

__all__ = [
    "PasswordPolicyError",
    "create_access_token",
    "decode_access_token",
    "hash_password",
    "make_password_record",
    "new_salt",
    "validate_password",
    "verify_password",
]
