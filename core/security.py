"""JWT issue/verify, OTP code generation + hashing, refresh-token generation
+ hashing. Pure crypto/token helpers — no DB or FastAPI imports, so they're
independently unit-testable.
"""
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt

from core.config import settings

ALGORITHM = "HS256"


# ── Access JWT ────────────────────────────────────────────────────────────
def create_access_token(*, user_id: uuid.UUID | str, email: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "email": email,
        "iat": int(now.timestamp()),
        "exp": now + timedelta(minutes=settings.JWT_ACCESS_TTL_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Raises jwt.PyJWTError (ExpiredSignatureError, InvalidTokenError, ...) on
    a bad/expired token — callers translate that into an UnauthorizedError."""
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[ALGORITHM])


# ── OTP codes ─────────────────────────────────────────────────────────────
def generate_otp_code() -> str:
    """6-digit numeric code, zero-padded."""
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def verify_otp_code(code: str, code_hash: str) -> bool:
    return secrets.compare_digest(hash_otp_code(code), code_hash)


# ── Refresh tokens ────────────────────────────────────────────────────────
def generate_refresh_token() -> str:
    """Long-lived opaque token — only its hash is ever persisted."""
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
