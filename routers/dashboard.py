"""Dashboard summary/charts + the trip-wide activity timeline.

Summary/charts recompute from every expense+settlement in the trip on each
call (no caching layer here) — see Backend/README.md "Scaling notes" for a
short-TTL caching recommendation once trip sizes grow.

Two routers live here because /timeline sits directly under `/trips/{tripId}`
rather than under `/trips/{tripId}/dashboard` (see CONTRACT.md's API table).
"""
from collections import defaultdict
from datetime import timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.deps import get_current_user, get_db, require_member
from models.expense import Expense, ExpenseSplit
from models.member import TripMember
from models.settlement import Settlement
from models.trip import Trip
from models.user import User
from schemas.dashboard import (
    CategoryBreakdown,
    DashboardChartsResponse,
    DashboardSummaryResponse,
    MemberBalance,
    MemberBreakdown,
    TimelineActivity,
    TimelinePoint,
)
from services.balance_service import compute_balances
from utils.pagination import decode_cursor, encode_cursor
from utils.responses import success_response

router = APIRouter(prefix="/trips/{tripId}/dashboard", tags=["dashboard"])
timeline_router = APIRouter(prefix="/trips/{tripId}", tags=["dashboard"])


def _member_ids(db: Session, trip_id) -> list[str]:
    return [
        str(m.user_id) for m in db.scalars(
            select(TripMember).where(TripMember.trip_id == trip_id, TripMember.status == "active")
        ).all()
    ]


def _member_names(db: Session, trip_id) -> dict[str, str]:
    rows = db.execute(
        select(TripMember.user_id, User.display_name, User.email)
        .join(User, User.id == TripMember.user_id)
        .where(TripMember.trip_id == trip_id)
    ).all()
    return {str(uid): (display_name or email) for uid, display_name, email in rows}


def _expenses_as_dicts(db: Session, trip_id) -> list[dict]:
    expenses = db.scalars(select(Expense).where(Expense.trip_id == trip_id)).all()
    expense_ids = [e.id for e in expenses]
    splits_by_expense: dict = defaultdict(list)
    if expense_ids:
        for split in db.scalars(select(ExpenseSplit).where(ExpenseSplit.expense_id.in_(expense_ids))).all():
            splits_by_expense[split.expense_id].append(split)
    return [
        {
            "id": str(e.id), "paidBy": str(e.paid_by), "amount": float(e.amount),
            "category": e.category, "date": e.date, "createdBy": str(e.created_by), "createdAt": e.created_at,
            "description": e.description,
            "splits": [{"uid": str(s.user_id), "amount": float(s.amount)} for s in splits_by_expense.get(e.id, [])],
        }
        for e in expenses
    ]


def _settlements_as_dicts(db: Session, trip_id) -> list[dict]:
    settlements = db.scalars(select(Settlement).where(Settlement.trip_id == trip_id)).all()
    return [
        {
            "id": str(s.id), "fromUid": str(s.from_user_id), "toUid": str(s.to_user_id), "amount": float(s.amount),
            "status": s.status, "settledBy": str(s.settled_by), "createdAt": s.created_at,
        }
        for s in settlements
    ]


@router.get("/summary")
def dashboard_summary(
    tripId: str, user: User = Depends(get_current_user), trip: Trip = Depends(require_member), db: Session = Depends(get_db)
):
    uid = str(user.id)
    expenses = _expenses_as_dicts(db, trip.id)
    settlements = _settlements_as_dicts(db, trip.id)
    member_ids = _member_ids(db, trip.id)
    names = _member_names(db, trip.id)

    balances = compute_balances(expenses, settlements, member_ids)
    total_expense = sum(e["amount"] for e in expenses)
    your_expense = sum(s["amount"] for e in expenses for s in e["splits"] if s["uid"] == uid)
    your_balance = balances.get(uid, 0.0)
    you_owe = -your_balance if your_balance < 0 else 0.0
    you_get = your_balance if your_balance > 0 else 0.0

    member_balances = [
        MemberBalance(uid=m, name=names.get(m, m), net=balances.get(m, 0.0)) for m in member_ids
    ]

    return success_response(DashboardSummaryResponse(
        totalExpense=round(total_expense, 2), yourExpense=round(your_expense, 2),
        youOwe=round(you_owe, 2), youGet=round(you_get, 2), memberBalances=member_balances,
    ).model_dump(mode="json"))


@router.get("/charts")
def dashboard_charts(tripId: str, trip: Trip = Depends(require_member), db: Session = Depends(get_db)):
    expenses = _expenses_as_dicts(db, trip.id)
    names = _member_names(db, trip.id)

    by_category: dict[str, float] = defaultdict(float)
    by_member: dict[str, float] = defaultdict(float)
    by_day: dict[str, float] = defaultdict(float)

    for e in expenses:
        by_category[e["category"] or "Uncategorized"] += e["amount"]
        by_member[e["paidBy"]] += e["amount"]
        by_day[e["date"].isoformat()] += e["amount"]

    return success_response(DashboardChartsResponse(
        byCategory=[CategoryBreakdown(category=c, amount=round(a, 2)) for c, a in sorted(by_category.items())],
        byMember=[MemberBreakdown(uid=u, name=names.get(u, u), amount=round(a, 2)) for u, a in by_member.items()],
        timeline=[TimelinePoint(date=d, amount=round(a, 2)) for d, a in sorted(by_day.items())],
    ).model_dump(mode="json"))


@timeline_router.get("/timeline")
def trip_timeline(
    tripId: str,
    trip: Trip = Depends(require_member),
    db: Session = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(default=None),
):
    """Merges expenses (as "expense_added" events) and settlements (as
    "settlement" events), sorted by createdAt desc, then truncated to one
    page in-process (trip activity volumes are small enough that this is
    simpler and correct, unlike the old two-sub-cursor Firestore scheme)."""
    names = _member_names(db, trip.id)
    expenses = _expenses_as_dicts(db, trip.id)
    settlements = _settlements_as_dicts(db, trip.id)

    activities = []
    for e in expenses:
        created_at = e["createdAt"]
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        activities.append({
            "id": e["id"], "type": "expense_added", "tripId": str(trip.id), "actorUid": e["createdBy"],
            "actorName": names.get(e["createdBy"], e["createdBy"]),
            "summary": e["description"], "amount": e["amount"], "createdAt": created_at,
        })
    for s in settlements:
        created_at = s["createdAt"]
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        from_name = names.get(s["fromUid"], s["fromUid"])
        to_name = names.get(s["toUid"], s["toUid"])
        activities.append({
            "id": s["id"], "type": "settlement", "tripId": str(trip.id), "actorUid": s["settledBy"],
            "actorName": names.get(s["settledBy"], s["settledBy"]),
            "summary": f"{from_name} paid {to_name}", "amount": s["amount"], "createdAt": created_at,
        })

    activities.sort(key=lambda a: a["createdAt"], reverse=True)

    cursor_value = decode_cursor(cursor)
    if cursor_value is not None:
        activities = [a for a in activities if a["createdAt"] < cursor_value]

    has_more = len(activities) > limit
    page = activities[:limit]
    next_cursor = encode_cursor(page[-1]["createdAt"]) if has_more and page else None

    result = [
        TimelineActivity(**{**a, "createdAt": a["createdAt"].isoformat()}).model_dump(mode="json")
        for a in page
    ]
    return success_response(result, meta={"cursor": next_cursor, "hasMore": has_more})
