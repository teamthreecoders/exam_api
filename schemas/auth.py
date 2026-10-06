from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class SignupRequest(BaseModel):
    first_name: str = Field(min_length=3)
    last_name: str = Field(min_length=3)
    email: EmailStr
    phone: str = Field(pattern=r"^\d{10}$")
    country_cd: str = Field(default="+91", pattern=r"^\+\d{2}$")
    role_type: Literal["user", "admin", "guest", "other"] = "user"


class SignupResponse(BaseModel):
    email: str
    email_verification_required: bool


class CredentialByEmail(BaseModel):
    email: EmailStr


class CredentialByPhone(BaseModel):
    country_cd: str
    phone: str


class CredentialByUserId(BaseModel):
    user_id: str


Credential = CredentialByEmail | CredentialByPhone | CredentialByUserId


class LoginRequest(BaseModel):
    credential: Credential
    password: str = Field(min_length=8)


class LoginResponse(BaseModel):
    """Either {token} (2FA disabled) or {mode, challenge_token} (2FA enabled,
    which is the default for every user on the auth service)."""

    token: str | None = None
    mode: str | None = None
    challenge_token: str | None = None


class TwoFAVerifyRequest(BaseModel):
    challenge_token: str
    otp: str = Field(min_length=4, max_length=4)


class ForgotPasswordRequest(BaseModel):
    credential: Credential


class ForgotPasswordResponse(BaseModel):
    email: str


class UserProfileResponse(BaseModel):
    user_id: str
    email: str
    first_name: str
    last_name: str | None = None
    is_active: bool
    role: str = "user"

    model_config = {"from_attributes": True}
