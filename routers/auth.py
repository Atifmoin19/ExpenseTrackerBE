"""Auth — backend-owned JWT auth (no Firebase): email OTP (via Resend),
Google Identity Services token verification, refresh-token rotation, and the
current-user profile endpoints. Exactly per CONTRACT.md's "Auth model" and
API table."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import settings
from core.database import get_db
from core.deps import get_current_user
from core.security import (
    create_access_token,
    generate_otp_code,
    generate_refresh_token,
    hash_otp_code,
    hash_refresh_token,
    verify_otp_code,
)
from models.otp import OtpCode
from models.refresh_token import RefreshToken
from models.user import User
from schemas.auth import (
    AuthResponse,
    GoogleAuthRequest,
    LogoutRequest,
    MeUpdateRequest,
    OtpRequestRequest,
    OtpRequestResponse,
    OtpVerifyRequest,
    RefreshRequest,
    TokenPairResponse,
    UserResponse,
)
from services import email_service, google_auth_service
from utils.exceptions import UnauthorizedError, ValidationError
from utils.responses import success_response

router = APIRouter(prefix="/auth", tags=["auth"])

OTP_TTL_MINUTES = 10
OTP_MAX_ATTEMPTS = 5


def _user_response(user: User) -> dict:
    return UserResponse(
        id=str(user.id), email=user.email, displayName=user.display_name, photoUrl=user.photo_url,
        createdAt=user.created_at, updatedAt=user.updated_at,
    ).model_dump(mode="json")


def _issue_token_pair(db: Session, user: User) -> TokenPairResponse:
    access_token = create_access_token(user_id=user.id, email=user.email)
    refresh_token = generate_refresh_token()
    now = datetime.now(timezone.utc)
    db.add(RefreshToken(
        user_id=user.id, token_hash=hash_refresh_token(refresh_token),
        expires_at=now + timedelta(days=settings.JWT_REFRESH_TTL_DAYS),
    ))
    db.commit()
    return TokenPairResponse(accessToken=access_token, refreshToken=refresh_token)


def _get_or_create_user(db: Session, *, email: str, display_name: str | None = None,
                         photo_url: str | None = None) -> User:
    user = db.scalar(select(User).where(User.email == email))
    if user is not None:
        changed = False
        if display_name and not user.display_name:
            user.display_name = display_name
            changed = True
        if photo_url and not user.photo_url:
            user.photo_url = photo_url
            changed = True
        if changed:
            db.commit()
            db.refresh(user)
        return user

    user = User(email=email, display_name=display_name or email.split("@")[0], photo_url=photo_url)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/otp/request")
def request_otp(body: OtpRequestRequest, db: Session = Depends(get_db)):
    """Always 200 — doesn't leak whether the email exists yet (the users row
    is only created on successful verify)."""
    email = body.email.lower()
    code = generate_otp_code()
    now = datetime.now(timezone.utc)

    db.add(OtpCode(email=email, code_hash=hash_otp_code(code), expires_at=now + timedelta(minutes=OTP_TTL_MINUTES)))
    db.commit()

    email_service.send_otp_email(to_email=email, code=code)

    debug_code = None
    if settings.is_development and not email_service.is_configured():
        debug_code = code

    return success_response(OtpRequestResponse(sent=True, debugCode=debug_code).model_dump(mode="json"))


@router.post("/otp/verify")
def verify_otp(body: OtpVerifyRequest, db: Session = Depends(get_db)):
    email = body.email.lower()
    otp_row = db.scalar(
        select(OtpCode).where(OtpCode.email == email).order_by(OtpCode.created_at.desc()).limit(1)
    )
    now = datetime.now(timezone.utc)
    if otp_row is None:
        raise ValidationError("No OTP was requested for this email")

    expires_at = otp_row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now:
        raise ValidationError("OTP has expired — request a new one")
    if otp_row.attempts >= OTP_MAX_ATTEMPTS:
        raise ValidationError("Too many incorrect attempts — request a new OTP")

    if not verify_otp_code(body.code, otp_row.code_hash):
        otp_row.attempts += 1
        db.commit()
        raise ValidationError("Incorrect OTP code")

    # Consume the code so it can't be replayed.
    db.delete(otp_row)
    db.commit()

    user = _get_or_create_user(db, email=email)
    tokens = _issue_token_pair(db, user)

    return success_response(AuthResponse(
        accessToken=tokens.accessToken, refreshToken=tokens.refreshToken, user=UserResponse(**_user_response(user)),
    ).model_dump(mode="json"))


@router.post("/google")
def google_login(body: GoogleAuthRequest, db: Session = Depends(get_db)):
    claims = google_auth_service.verify_google_id_token(body.idToken)
    email = claims["email"].lower()
    user = _get_or_create_user(db, email=email, display_name=claims.get("name"), photo_url=claims.get("picture"))
    tokens = _issue_token_pair(db, user)

    return success_response(AuthResponse(
        accessToken=tokens.accessToken, refreshToken=tokens.refreshToken, user=UserResponse(**_user_response(user)),
    ).model_dump(mode="json"))


@router.post("/refresh")
def refresh_token(body: RefreshRequest, db: Session = Depends(get_db)):
    token_hash = hash_refresh_token(body.refreshToken)
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    now = datetime.now(timezone.utc)

    if row is None:
        raise UnauthorizedError("Invalid refresh token")
    expires_at = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
    if row.revoked_at is not None or expires_at < now:
        raise UnauthorizedError("Refresh token has expired or been revoked")

    user = db.get(User, row.user_id)
    if user is None:
        raise UnauthorizedError("User no longer exists")

    row.revoked_at = now
    db.commit()

    tokens = _issue_token_pair(db, user)
    return success_response(tokens.model_dump(mode="json"))


@router.post("/logout")
def logout(body: LogoutRequest, db: Session = Depends(get_db)):
    token_hash = hash_refresh_token(body.refreshToken)
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    if row is not None and row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        db.commit()
    return success_response({"loggedOut": True})


@router.get("/me")
def get_me(user: User = Depends(get_current_user)):
    return success_response(_user_response(user))


@router.patch("/me")
def update_me(body: MeUpdateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    updates = body.model_dump(exclude_unset=True)
    if "displayName" in updates:
        user.display_name = updates["displayName"]
    if "photoUrl" in updates:
        user.photo_url = updates["photoUrl"]
    db.commit()
    db.refresh(user)
    return success_response(_user_response(user))
