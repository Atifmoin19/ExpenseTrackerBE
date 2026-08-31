from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class OtpRequestRequest(BaseModel):
    email: EmailStr


class OtpRequestResponse(BaseModel):
    """Always 200 — never leaks whether the email exists. `debugCode` is only
    populated in development when EmailJS isn't configured, so local
    testing works end-to-end without a real EmailJS account."""
    sent: bool = True
    debugCode: str | None = None


class OtpVerifyRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6)


class GoogleAuthRequest(BaseModel):
    idToken: str = Field(min_length=1)


class RefreshRequest(BaseModel):
    refreshToken: str = Field(min_length=1)


class LogoutRequest(BaseModel):
    refreshToken: str = Field(min_length=1)


class UserResponse(BaseModel):
    id: str
    email: str
    displayName: str | None = None
    photoUrl: str | None = None
    createdAt: datetime
    updatedAt: datetime


class TokenPairResponse(BaseModel):
    accessToken: str
    refreshToken: str


class AuthResponse(TokenPairResponse):
    user: UserResponse


class MeUpdateRequest(BaseModel):
    displayName: str | None = Field(default=None, min_length=1, max_length=200)
    photoUrl: str | None = None
