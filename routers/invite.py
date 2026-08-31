"""Invites — trip admins create/reuse an invite code; anyone can preview it
(public, no auth); an authenticated user accepts it to join the trip.

Two APIRouters live in this module because the paths sit under two different
prefixes (`/trips/{tripId}/invites` vs `/invites/{code}`) — both are mounted
in main.py.
"""
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.deps import get_current_user, get_db, require_admin
from models.invite import Invite, InviteUse
from models.member import TripMember
from models.trip import Trip
from models.user import User
from schemas.invite import InviteAcceptResponse, InviteCreateRequest, InviteCreateResponse, InvitePreviewResponse
from services.push_service import send_notification
from utils.exceptions import NotFoundError, ValidationError
from utils.responses import success_response

trip_invites_router = APIRouter(prefix="/trips/{tripId}/invites", tags=["invites"])
invites_router = APIRouter(prefix="/invites", tags=["invites"])


def _generate_code() -> str:
    return secrets.token_urlsafe(8).replace("_", "").replace("-", "")[:8]


def _as_aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


@trip_invites_router.post("")
def create_invite(
    tripId: str, body: InviteCreateRequest = InviteCreateRequest(), user: User = Depends(get_current_user),
    trip: Trip = Depends(require_admin), db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)

    # Reuse an existing, still-valid invite created by this admin for this trip.
    existing = db.scalars(
        select(Invite).where(Invite.trip_id == trip.id, Invite.created_by == user.id)
    ).all()
    for invite in existing:
        if _as_aware(invite.expires_at) > now:
            return success_response(InviteCreateResponse(
                code=invite.code, tripId=str(trip.id), expiresAt=invite.expires_at, maxUses=invite.max_uses,
                inviteUrl=f"https://app.com/invite/{invite.code}",
            ).model_dump(mode="json"))

    code = _generate_code()
    expires_at = now + timedelta(days=body.expiresInDays)
    invite = Invite(
        code=code, trip_id=trip.id, created_by=user.id, expires_at=expires_at, max_uses=body.maxUses,
    )
    db.add(invite)
    db.commit()

    return success_response(InviteCreateResponse(
        code=code, tripId=str(trip.id), expiresAt=expires_at, maxUses=body.maxUses,
        inviteUrl=f"https://app.com/invite/{code}",
    ).model_dump(mode="json"))


@invites_router.get("/{code}")
def preview_invite(code: str, db: Session = Depends(get_db)):
    invite = db.get(Invite, code)
    if invite is None:
        raise NotFoundError("Invite not found")

    trip = db.get(Trip, invite.trip_id)
    if trip is None:
        raise NotFoundError("Trip no longer exists")

    member_count = len(db.scalars(
        select(TripMember).where(TripMember.trip_id == trip.id, TripMember.status == "active")
    ).all())

    return success_response(InvitePreviewResponse(
        tripId=str(trip.id), tripName=trip.name,
        startDate=datetime.combine(trip.start_date, datetime.min.time(), tzinfo=timezone.utc),
        endDate=datetime.combine(trip.end_date, datetime.min.time(), tzinfo=timezone.utc),
        memberCount=member_count, expiresAt=invite.expires_at,
    ).model_dump(mode="json"))


@invites_router.post("/{code}/accept")
def accept_invite(code: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    invite = db.get(Invite, code)
    if invite is None:
        raise NotFoundError("Invite not found")

    now = datetime.now(timezone.utc)
    if _as_aware(invite.expires_at) < now:
        raise ValidationError("Invite has expired")

    use_count = len(db.scalars(select(InviteUse).where(InviteUse.invite_code == code)).all())
    if invite.max_uses and use_count >= invite.max_uses:
        raise ValidationError("Invite has reached its maximum uses")

    trip = db.get(Trip, invite.trip_id)
    if trip is None:
        raise NotFoundError("Trip no longer exists")

    membership = db.get(TripMember, (trip.id, user.id))
    if membership is None:
        db.add(TripMember(trip_id=trip.id, user_id=user.id, role="member", status="active"))
        db.commit()

        admins = db.scalars(
            select(TripMember).where(TripMember.trip_id == trip.id, TripMember.role == "admin", TripMember.status == "active")
        ).all()
        for admin in admins:
            send_notification(
                db, user_id=admin.user_id, trip_id=trip.id, type_="member_joined",
                title="New member joined", body=f"{user.display_name or user.email} joined {trip.name}",
            )
    elif membership.status != "active":
        membership.status = "active"
        db.commit()

    if db.get(InviteUse, (code, user.id)) is None:
        db.add(InviteUse(invite_code=code, user_id=user.id))
        db.commit()

    return success_response(InviteAcceptResponse(tripId=str(trip.id), joined=True).model_dump(mode="json"))
