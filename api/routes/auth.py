from fastapi import APIRouter, Depends, HTTPException, Response

from core.config import settings
from models.user import User
from schemas.auth import (
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LoginRequest,
    LoginResponse,
    SignupRequest,
    SignupResponse,
    TwoFAVerifyRequest,
    UserProfileResponse,
)
from services.auth_cache import session_cache
from services.auth_client import AuthServiceError, auth_service_client

from api.deps import get_current_user, get_session_token

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        settings.SESSION_COOKIE_NAME,
        token,
        httponly=True,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite=settings.SESSION_COOKIE_SAMESITE,
    )


@router.post("/signup", response_model=SignupResponse, status_code=201)
def signup(payload: SignupRequest) -> dict:
    try:
        return auth_service_client.signup(payload.model_dump())
    except AuthServiceError as exc:
        raise HTTPException(exc.status_code, exc.msg) from exc


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, response: Response) -> dict:
    try:
        data = auth_service_client.login(payload.model_dump(mode="json"))
    except AuthServiceError as exc:
        raise HTTPException(exc.status_code, exc.msg) from exc

    # 2FA is enabled by default for every account, so in practice this
    # response is always {mode, challenge_token} and login only completes
    # after /login/2fa-verify. But if an account ever has 2FA disabled, the
    # auth service returns a session token directly here -- set our cookie
    # in that case too, or that account could never actually log in.
    if data.get("token"):
        _set_session_cookie(response, data["token"])
    return data


@router.post("/login/2fa-verify", response_model=LoginResponse)
def verify_2fa(payload: TwoFAVerifyRequest, response: Response) -> dict:
    try:
        data = auth_service_client.verify_2fa(payload.model_dump())
    except AuthServiceError as exc:
        raise HTTPException(exc.status_code, exc.msg) from exc

    _set_session_cookie(response, data["token"])
    return data


@router.post("/forgot-password", response_model=ForgotPasswordResponse, status_code=202)
def forgot_password(payload: ForgotPasswordRequest) -> dict:
    try:
        return auth_service_client.forgot_password(payload.model_dump(mode="json"))
    except AuthServiceError as exc:
        raise HTTPException(exc.status_code, exc.msg) from exc


@router.get("/me", response_model=UserProfileResponse)
def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.post("/logout")
def logout(response: Response, token: str = Depends(get_session_token)) -> dict:
    auth_service_client.logout(token)
    session_cache.invalidate(token)
    response.delete_cookie(settings.SESSION_COOKIE_NAME)
    return {"msg": "Logged out"}
