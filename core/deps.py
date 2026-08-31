"""Shared FastAPI dependencies: current-user resolution and trip admin/member
guards, backed by Postgres via SQLAlchemy."""
import uuid

import jwt
from fastapi import Depends, Header
from sqlalchemy.orm import Session

from core.database import get_db
from core.security import decode_access_token
from models.member import TripMember
from models.trip import Trip
from models.user import User
from utils.exceptions import ForbiddenError, NotFoundError, UnauthorizedError

__all__ = ["get_db", "get_current_user", "require_admin", "require_member"]


def get_current_user(
    authorization: str | None = Header(default=None), db: Session = Depends(get_db)
) -> User:
    """Verifies the access JWT from the Authorization header and loads the
    caller's `users` row — no external call needed (unlike Firebase token
    verification)."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise UnauthorizedError("Missing or malformed Authorization header. Expected 'Bearer <accessToken>'.")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise UnauthorizedError("Missing bearer token")

    try:
        claims = decode_access_token(token)
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("Access token has expired") from exc
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("Invalid access token") from exc

    try:
        user_id = uuid.UUID(claims["sub"])
    except (KeyError, ValueError, TypeError) as exc:
        raise UnauthorizedError("Invalid access token") from exc

    user = db.get(User, user_id)
    if user is None:
        raise UnauthorizedError("User no longer exists")
    return user


def _get_trip_or_404(db: Session, trip_id: str) -> Trip:
    try:
        trip_uuid = uuid.UUID(trip_id)
    except ValueError as exc:
        raise NotFoundError("Trip not found") from exc
    trip = db.get(Trip, trip_uuid)
    if trip is None:
        raise NotFoundError("Trip not found")
    return trip


def require_member(
    tripId: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Trip:
    """Dependency: 404 if the trip doesn't exist, 403 unless the caller
    belongs to it. Returns the Trip ORM row."""
    trip = _get_trip_or_404(db, tripId)
    membership = db.get(TripMember, (trip.id, user.id))
    if membership is None or membership.status != "active":
        raise ForbiddenError("You are not a member of this trip")
    return trip


def require_admin(
    tripId: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Trip:
    """Dependency: 404 if the trip doesn't exist, 403 unless the caller is a
    trip admin. Returns the Trip ORM row."""
    trip = _get_trip_or_404(db, tripId)
    membership = db.get(TripMember, (trip.id, user.id))
    if membership is None or membership.status != "active" or membership.role != "admin":
        raise ForbiddenError("Only trip admins can perform this action")
    return trip
