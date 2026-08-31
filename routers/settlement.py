"""Settlements — mark a payment settled, list settlements, and the
min-transaction "suggested settlements" optimizer output."""
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.deps import get_current_user, get_db, require_member
from models.member import TripMember
from models.settlement import Settlement
from models.trip import Trip
from models.user import User
from schemas.settlement import SettlementCreateRequest, SettlementResponse, SuggestedSettlement
from services.balance_service import load_trip_balances
from services.push_service import send_notification
from services.settlement_engine import optimize
from utils.exceptions import ValidationError
from utils.pagination import paginate
from utils.responses import success_response

router = APIRouter(prefix="/trips/{tripId}/settlements", tags=["settlements"])


def _active_member_ids(db: Session, trip_id) -> set[str]:
    return {
        str(m.user_id) for m in db.scalars(
            select(TripMember).where(TripMember.trip_id == trip_id, TripMember.status == "active")
        ).all()
    }


def _settlement_response(settlement: Settlement, trip_id) -> dict:
    return SettlementResponse(
        id=str(settlement.id), tripId=str(trip_id), fromUid=str(settlement.from_user_id),
        toUid=str(settlement.to_user_id), amount=float(settlement.amount), method=settlement.method,
        note=settlement.note, settledBy=str(settlement.settled_by), status=settlement.status,
        createdAt=settlement.created_at,
    ).model_dump(mode="json")


@router.post("")
def create_settlement(
    tripId: str, body: SettlementCreateRequest, user: User = Depends(get_current_user),
    trip: Trip = Depends(require_member), db: Session = Depends(get_db),
):
    member_ids = _active_member_ids(db, trip.id)
    if body.fromUid not in member_ids or body.toUid not in member_ids:
        raise ValidationError("fromUid and toUid must both be members of this trip")

    settlement = Settlement(
        trip_id=trip.id, from_user_id=uuid.UUID(body.fromUid), to_user_id=uuid.UUID(body.toUid),
        amount=body.amount, method=body.method, note=body.note, settled_by=user.id, status="completed",
    )
    db.add(settlement)
    db.commit()
    db.refresh(settlement)

    send_notification(
        db, user_id=uuid.UUID(body.toUid), trip_id=trip.id, type_="settlement_recorded",
        title="Payment settled", body=f"{body.amount} {trip.currency} settlement recorded",
    )

    return success_response(_settlement_response(settlement, trip.id))


@router.get("")
def list_settlements(
    tripId: str, trip: Trip = Depends(require_member), db: Session = Depends(get_db),
    limit: int = Query(20, ge=1, le=100), cursor: str | None = Query(default=None),
):
    stmt = select(Settlement).where(Settlement.trip_id == trip.id)
    items, has_more, next_cursor = paginate(db, stmt, Settlement.created_at, limit=limit, cursor=cursor)
    return success_response(
        [_settlement_response(s, trip.id) for s in items], meta={"cursor": next_cursor, "hasMore": has_more}
    )


@router.get("/suggested")
def suggested_settlements(tripId: str, trip: Trip = Depends(require_member), db: Session = Depends(get_db)):
    member_ids = [m.user_id for m in db.scalars(
        select(TripMember).where(TripMember.trip_id == trip.id, TripMember.status == "active")
    ).all()]
    balances = load_trip_balances(db, trip.id, member_ids)
    suggestions = optimize(balances)
    return success_response([SuggestedSettlement(**s).model_dump(mode="json") for s in suggestions])
