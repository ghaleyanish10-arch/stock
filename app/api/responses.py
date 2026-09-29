"""Shared API response envelope: every endpoint answers in one shape."""

from __future__ import annotations

from typing import Any, Optional

from fastapi.responses import JSONResponse

from app.nepse.exceptions import NepseServiceError


class ApiErrorBody(dict):
    """Convenience wrapper for building the `error` object."""

    @classmethod
    def build(cls, code: str, message: str) -> dict:
        return {"code": code, "message": message}


def ok(data: Any) -> dict:
    """Build a successful response body."""
    return {"success": True, "data": data}


def fail(code: str, message: str) -> dict:
    """Build a failed response body."""
    return {"success": False, "error": {"code": code, "message": message}}


def nepse_error_response(exc: NepseServiceError) -> JSONResponse:
    """Map an application NEPSE error to the standard envelope + status."""
    status_by_code = {
        "NEPSE_UNAVAILABLE": 503,
        "NEPSE_TIMEOUT": 504,
        "NEPSE_INVALID_RESPONSE": 502,
        "NEPSE_AUTH_FAILED": 502,
        "NEPSE_RATE_LIMITED": 429,
        "NEPSE_SYMBOL_NOT_FOUND": 404,
        "NEPSE_DATA_NOT_FOUND": 404,
    }
    return JSONResponse(
        status_code=status_by_code.get(exc.code, 502),
        content=fail(exc.code, exc.message),
    )
