"""Trips — create/list/get/update/delete, plus the expense-permission settings
sub-resource. Creator becomes the sole admin+member at creation time."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.deps import get_current_user, get_db, require_admin, require_member
from models.member import TripAllowedExpenseMember, TripMember
from models.trip import Trip
from models.user import User
from schemas.trip import TripCreateRequest, TripResponse, TripSettingsUpdateRequest, TripUpdateRequest
from utils.pagination import paginate
from utils.responses import success_response

router = APIRouter(prefix="/trips", tags=["trips"])


def _trip_response(db: Session, trip: Trip) -> dict:
    memberships = db.scalars(
        select(TripMember).where(TripMember.trip_id == trip.id, TripMember.status == "active")
    ).all()
    admin_ids = [str(m.user_id) for m in memberships if m.role == "admin"]
    member_ids = [str(m.user_id) for m in memberships]
    allowed_ids = [
        str(a.user_id) for a in db.scalars(
            select(TripAllowedExpenseMember).where(TripAllowedExpenseMember.trip_id == trip.id)
        ).all()
    ]
    return TripResponse(
        id=str(trip.id), name=trip.name, description=trip.description,
        startDate=datetime.combine(trip.start_date, datetime.min.time(), tzinfo=timezone.utc),
        endDate=datetime.combine(trip.end_date, datetime.min.time(), tzinfo=timezone.utc),
        currency=trip.currency, createdBy=str(trip.created_by), adminIds=admin_ids, memberIds=member_ids,
        expensePermission=trip.expense_permission, allowedMemberIds=allowed_ids, status=trip.status,
        createdAt=trip.created_at, updatedAt=trip.updated_at,
    ).model_dump(mode="json")


@router.post("")
def create_trip(body: TripCreateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    trip = Trip(
        name=body.name, description=body.description, start_date=body.startDate, end_date=body.endDate,
        currency=body.currency, created_by=user.id, expense_permission="admin_only", status="active",
    )
    db.add(trip)
    db.flush()  # assigns trip.id without committing yet

    db.add(TripMember(trip_id=trip.id, user_id=user.id, role="admin", status="active"))
    db.commit()
    db.refresh(trip)

    return success_response(_trip_response(db, trip))


@router.get("")
def list_trips(
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
    limit: int = Query(20, ge=1, le=100), cursor: str | None = Query(default=None),
):
    stmt = (
        select(Trip)
        .join(TripMember, TripMember.trip_id == Trip.id)
        .where(TripMember.user_id == user.id, TripMember.status == "active")
    )
    items, has_more, next_cursor = paginate(db, stmt, Trip.created_at, limit=limit, cursor=cursor)
    return success_response(
        [_trip_response(db, t) for t in items], meta={"cursor": next_cursor, "hasMore": has_more}
    )


@router.get("/{tripId}")
def get_trip(tripId: str, trip: Trip = Depends(require_member), db: Session = Depends(get_db)):
    return success_response(_trip_response(db, trip))


@router.patch("/{tripId}")
def update_trip(
    tripId: str, body: TripUpdateRequest, trip: Trip = Depends(require_admin), db: Session = Depends(get_db)
):
    updates = body.model_dump(exclude_unset=True)
    if "name" in updates:
        trip.name = updates["name"]
    if "description" in updates:
        trip.description = updates["description"]
    if "startDate" in updates:
        trip.start_date = updates["startDate"]
    if "endDate" in updates:
        trip.end_date = updates["endDate"]
    if "currency" in updates:
        trip.currency = updates["currency"]
    if "status" in updates:
        trip.status = updates["status"]
    db.commit()
    db.refresh(trip)
    return success_response(_trip_response(db, trip))


@router.delete("/{tripId}")
def delete_trip(tripId: str, trip: Trip = Depends(require_admin), db: Session = Depends(get_db)):
    db.delete(trip)
    db.commit()
    return success_response({"id": tripId, "deleted": True})


@router.patch("/{tripId}/settings")
def update_trip_settings(
    tripId: str, body: TripSettingsUpdateRequest, trip: Trip = Depends(require_admin), db: Session = Depends(get_db)
):
    trip.expense_permission = body.expensePermission
    db.query(TripAllowedExpenseMember).filter(TripAllowedExpenseMember.trip_id == trip.id).delete()
    for uid in body.allowedMemberIds:
        db.add(TripAllowedExpenseMember(trip_id=trip.id, user_id=uid))
    db.commit()
    db.refresh(trip)
    return success_response(_trip_response(db, trip))
