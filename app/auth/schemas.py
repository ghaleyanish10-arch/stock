"""Pydantic schemas for the auth API."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=1, max_length=256)
    display_name: Optional[str] = Field(None, max_length=120)

    @field_validator("email")
    @classmethod
    def normalise_email(cls, value: str) -> str:
        value = value.strip().lower()
        # Deliberately loose: the goal is to catch typos, not to re-implement
        # RFC 5322. Real validation happens at the mail-verification step.
        if value.count("@") != 1 or value.startswith("@") or value.endswith("@"):
            raise ValueError("Enter a valid email address.")
        local, _, domain = value.partition("@")
        if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
            raise ValueError("Enter a valid email address.")
        return value


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    password: str

    @field_validator("email")
    @classmethod
    def normalise_email(cls, value: str) -> str:
        return value.strip().lower()


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: str
    user: "UserResponse"


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    display_name: Optional[str] = None
    is_admin: bool = False
    theme: Optional[str] = None
    created_at: Optional[str] = None

    @field_validator("created_at", mode="before")
    @classmethod
    def _stringify_created_at(cls, value):
        if isinstance(value, datetime):
            return value.isoformat()
        return value


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str
    new_password: str = Field(..., min_length=1, max_length=256)


class ThemeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme: str = Field(..., pattern="^(light|dark|system)$")


TokenResponse.model_rebuild()
