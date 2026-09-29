"""Auth routes: register, sign in, whoami, profile, password, sign out."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.auth.deps import CurrentUser, DbSession
from app.auth.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    RegisterRequest,
    ThemeRequest,
    TokenResponse,
    UserResponse,
)
from app.auth.security import (
    PasswordPolicyError,
    create_access_token,
    make_password_record,
    verify_password,
)
from app.db.models import User
from app.db.base import utcnow

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

#: Brute-force guard: a real deployment puts a rate limiter in front of these
#: routes (see docs/setup.md). We cap in-memory attempts per email to blunt
#: trivial online guessing.
_MAX_FAILED_ATTEMPTS = 10
_failed_attempts: dict[str, int] = {}


def _issue(user: User) -> TokenResponse:
    token, expires = create_access_token(
        user_id=user.id, email=user.email, token_version=user.token_version
    )
    return TokenResponse(
        access_token=token,
        expires_at=expires.isoformat(),
        user=UserResponse.model_validate(user),
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account with email and password",
)
def register(payload: RegisterRequest, session: DbSession) -> TokenResponse:
    existing = session.scalar(select(User).where(User.email == payload.email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists.",
        )
    try:
        salt, digest = make_password_record(payload.password)
    except PasswordPolicyError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    user = User(
        email=payload.email,
        password_salt=salt,
        password_hash=digest,
        display_name=(payload.display_name or "").strip() or None,
    )
    session.add(user)
    try:
        session.commit()
    except IntegrityError as exc:  # concurrent signup for the same email
        session.rollback()
        logger.info("duplicate signup for %s", payload.email)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists.",
        ) from exc

    logger.info("registered %s", user.email)
    return _issue(user)


@router.post("/login", response_model=TokenResponse, summary="Sign in")
def login(payload: LoginRequest, session: DbSession) -> TokenResponse:
    user = session.scalar(select(User).where(User.email == payload.email))

    # Verify against a dummy hash when the user is unknown so that a missing
    # account and a wrong password take the same time (no user enumeration).
    if user is None:
        _burn_password_time()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email or password is incorrect.",
        )

    if not verify_password(payload.password, user.password_salt, user.password_hash):
        attempts = _failed_attempts.get(user.email, 0) + 1
        _failed_attempts[user.email] = attempts
        if attempts >= _MAX_FAILED_ATTEMPTS:
            logger.warning("too many failed logins for %s", user.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email or password is incorrect.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="This account is disabled."
        )

    _failed_attempts.pop(user.email, None)
    user.last_login_at = utcnow()
    session.commit()
    return _issue(user)


def _burn_password_time() -> None:
    """Spend comparable time to a real verification on unknown accounts."""
    from app.auth.security import hash_password, new_salt

    try:
        hash_password("not-a-real-password", new_salt())
    except Exception:  # pragma: no cover - defensive
        logger.debug("dummy hash failed", exc_info=True)


@router.get("/me", response_model=UserResponse, summary="Current account")
def me(user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(user)


@router.patch("/me", response_model=UserResponse, summary="Update profile")
def update_me(payload: ThemeRequest, user: CurrentUser, session: DbSession) -> UserResponse:
    user.theme = payload.theme
    session.commit()
    return UserResponse.model_validate(user)


@router.post(
    "/change-password",
    response_model=TokenResponse,
    summary="Change password and re-issue the session",
)
def change_password(
    payload: ChangePasswordRequest, user: CurrentUser, session: DbSession
) -> TokenResponse:
    if not verify_password(payload.current_password, user.password_salt, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect."
        )
    try:
        salt, digest = make_password_record(payload.new_password)
    except PasswordPolicyError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    user.password_salt = salt
    user.password_hash = digest
    # Force every existing device to sign in again.
    user.token_version += 1
    session.commit()
    return _issue(user)


@router.post("/logout", status_code=status.HTTP_200_OK, summary="Sign out everywhere")
def logout(user: CurrentUser, session: DbSession) -> dict:
    user.token_version += 1
    session.commit()
    return {
        "detail": "Signed out. All existing sessions were invalidated.",
        "at": datetime.now(timezone.utc).isoformat(),
    }
