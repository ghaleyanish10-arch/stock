"""Auth dependencies: extract the bearer token and load the user."""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.security import decode_access_token
from app.db.models import User
from app.db.session import get_session

# auto_error=False so a missing header produces our own JSON error shape
# rather than FastAPI's default 403 body.
bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")

DbSession = Annotated[Session, Depends(get_session)]


def get_current_user(
    session: DbSession,
    credentials: Annotated[
        Optional[HTTPAuthorizationCredentials], Depends(bearer_scheme)
    ] = None,
) -> User:
    """Return the authenticated user, or raise 401.

    Two independent checks:
      1. the token must be signed, unexpired and of type `access`;
      2. `ver` must match the user's current `token_version`, so bumping the
         version (sign-out everywhere) invalidates existing tokens.
    """
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Sign in to continue.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or not credentials.credentials:
        raise unauthorized

    payload = decode_access_token(credentials.credentials)
    if not payload or not payload.get("sub"):
        raise unauthorized

    user = session.get(User, payload["sub"])
    if user is None:
        raise unauthorized
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="This account is disabled."
        )
    if int(payload.get("ver", -1)) != user.token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your session has expired. Sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_optional_user(
    session: DbSession,
    credentials: Annotated[
        Optional[HTTPAuthorizationCredentials], Depends(bearer_scheme)
    ] = None,
) -> Optional[User]:
    """Same as `get_current_user` but returns None instead of raising.

    Used by endpoints that show more detail to a signed-in user (saved
    screenshots, personal watchlists) but still work anonymously.
    """
    if credentials is None or not credentials.credentials:
        return None
    payload = decode_access_token(credentials.credentials)
    if not payload or not payload.get("sub"):
        return None
    user = session.get(User, payload["sub"])
    if user is None or not user.is_active:
        return None
    if int(payload.get("ver", -1)) != user.token_version:
        return None
    return user


OptionalUser = Annotated[Optional[User], Depends(get_optional_user)]


def require_admin(user: CurrentUser) -> User:
    """Guard for operational endpoints such as running a backfill."""
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires an administrator account.",
        )
    return user


AdminUser = Annotated[User, Depends(require_admin)]
