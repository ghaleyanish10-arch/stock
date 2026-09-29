"""Declarative base and portable column helpers.

Everything here is written so the same DDL runs on SQLite and PostgreSQL:
no SQLite-only column types, no `AUTOINCREMENT` assumptions, no SQLite
`ENUM`. Two rules:

* External dates (NEPSE business dates) are stored as `String(10)` holding an
  ISO `YYYY-MM-DD` value. It sorts and compares correctly as text, matches
  the format NEPSE actually returns, and needs no parsing layer.
* Internal timestamps are `DateTime` holding **naive UTC**, because SQLite
  has no timestamp-with-timezone type and silently corrupts offset-aware
  values. Use `utcnow()` to produce them.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, Enum as SAEnum, String
from sqlalchemy.orm import DeclarativeBase

from app.core.provenance import ValueStatus


class Base(DeclarativeBase):
    """Declarative base for every ORM model."""


def new_id() -> str:
    """Portable 36-char identifier (UUID4 hex)."""
    return uuid.uuid4().hex


def utcnow() -> datetime:
    """Current time as naive UTC, for `DateTime` columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso_date(value: Any) -> str | None:
    """Normalize a date/datetime/str to an ISO `YYYY-MM-DD` string."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, str):
        return value[:10]
    return value.isoformat()[:10]


#: Enum columns are created as VARCHAR everywhere (native_enum=False) so the
#: schema is identical on SQLite and PostgreSQL and adding a value later does
#: not require an ALTER TYPE migration.
status_enum = SAEnum(
    ValueStatus,
    name="value_status",
    native_enum=False,
    validate_strings=True,
    length=32,
)
side_enum = SAEnum(
    "buy", "sell", name="transaction_side", native_enum=False, validate_strings=True, length=8
)
