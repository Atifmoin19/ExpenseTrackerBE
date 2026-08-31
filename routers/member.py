"""Trip members — add by email, remove, change role. All admin-only."""
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.deps import get_db, require_admin, require_member
from models.member import TripMember
from models.trip import Trip
from models.user import User
from schemas.member import MemberAddRequest, MemberResponse, MemberRoleUpdateRequest
from services.push_service import send_notification
from utils.exceptions import ConflictError, NotFoundError, ValidationError
from utils.responses import success_response

router = APIRouter(prefix="/trips/{tripId}/members", tags=["members"])


def _get_membership_or_404(db: Session, trip_id, uid: str) -> TripMember:
    try:
        user_uuid = uuid.UUID(uid)
    except ValueError as exc:
        raise NotFoundError("Member not found in this trip") from exc
    member = db.get(TripMember, (trip_id, user_uuid))
    if member is None or member.status != "active":
        raise NotFoundError("Member not found in this trip")
    return member


def _member_response(member: TripMember, user: User) -> dict:
    return MemberResponse(
        uid=str(member.user_id), role=member.role, displayName=user.display_name, photoUrl=user.photo_url,
        joinedAt=member.joined_at, status=member.status,
    ).model_dump(mode="json")


@router.get("")
def list_members(tripId: str, trip: Trip = Depends(require_member), db: Session = Depends(get_db)):
    rows = db.execute(
        select(TripMember, User)
        .join(User, User.id == TripMember.user_id)
        .where(TripMember.trip_id == trip.id, TripMember.status == "active")
        .order_by(TripMember.joined_at)
    ).all()
    return success_response([_member_response(member, user) for member, user in rows])


@router.post("")
def add_member(tripId: str, body: MemberAddRequest, trip: Trip = Depends(require_admin), db: Session = Depends(get_db)):
    target = db.scalar(select(User).where(User.email == str(body.email).lower()))
    if target is None:
        raise NotFoundError("No registered user found with that email")

    existing = db.get(TripMember, (trip.id, target.id))
    if existing is not None and existing.status == "active":
        raise ConflictError("User is already a member of this trip")

    if existing is not None:
        existing.status = "active"
        member = existing
    else:
        member = TripMember(trip_id=trip.id, user_id=target.id, role="member", status="active")
        db.add(member)
    db.commit()
    db.refresh(member)

    admins = db.scalars(
        select(TripMember).where(TripMember.trip_id == trip.id, TripMember.role == "admin", TripMember.status == "active")
    ).all()
    for admin in admins:
        send_notification(
            db, user_id=admin.user_id, trip_id=trip.id, type_="member_joined",
            title="New member joined",
            body=f"{target.display_name or target.email} joined {trip.name}",
        )

    return success_response(_member_response(member, target))


@router.delete("/{uid}")
def remove_member(tripId: str, uid: str, trip: Trip = Depends(require_admin), db: Session = Depends(get_db)):
    member = _get_membership_or_404(db, trip.id, uid)
    if str(member.user_id) == str(trip.created_by):
        raise ValidationError("Cannot remove the trip creator")

    member.status = "removed"
    if member.role == "admin":
        member.role = "member"
    db.commit()
    return success_response({"uid": uid, "removed": True})


@router.patch("/{uid}/role")
def update_member_role(
    tripId: str, uid: str, body: MemberRoleUpdateRequest, trip: Trip = Depends(require_admin), db: Session = Depends(get_db)
):
    member = _get_membership_or_404(db, trip.id, uid)
    if body.role == "member" and str(member.user_id) == str(trip.created_by):
        raise ValidationError("Cannot demote the trip creator")

    member.role = body.role
    db.commit()
    db.refresh(member)
    target = db.get(User, member.user_id)
    return success_response(_member_response(member, target))
