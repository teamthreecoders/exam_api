from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from core.config import settings
from database.session import get_db
from models.user import User
from services.auth_cache import session_cache
from services.auth_client import AuthServiceError, auth_service_client


def get_session_token(request: Request) -> str:
    """Accepts the session token either as `Authorization: Bearer <token>`
    (the frontend calls the auth service directly and forwards its JWT this
    way) or as our own session cookie (still set by api/routes/auth.py for
    anything that proxies through it instead)."""
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        return auth_header[len("Bearer ") :]

    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return token


def get_current_user(
    token: str = Depends(get_session_token),
    db: Session = Depends(get_db),
) -> User:
    profile = session_cache.get(token)
    if profile is None:
        try:
            profile = auth_service_client.get_me(token)
        except AuthServiceError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, exc.msg) from exc
        session_cache.set(token, profile)

    user = db.get(User, profile["user_id"])
    if user is None:
        user = User(
            user_id=profile["user_id"],
            email=profile["email"],
            first_name=profile["first_name"],
            last_name=profile.get("last_name"),
            is_active=profile.get("is_active", True),
        )
        db.add(user)
    else:
        user.email = profile["email"]
        user.first_name = profile["first_name"]
        user.last_name = profile.get("last_name")
        user.is_active = profile.get("is_active", True)
    db.commit()
    db.refresh(user)
    return user
