"""Expenses — create (enforces trip.expensePermission), list (paginated +
filters), get, update/delete (creator-or-admin only)."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.deps import get_current_user, get_db, require_member
from models.expense import Expense, ExpenseSplit
from models.member import TripAllowedExpenseMember, TripMember
from models.trip import Trip
from models.user import User
from schemas.expense import (
    ExpenseCreateRequest,
    ExpenseResponse,
    ExpenseUpdateRequest,
    SplitInput,
    resolve_splits,
    validate_splits,
)
from services.push_service import send_notification
from utils.exceptions import ForbiddenError, NotFoundError, ValidationError
from utils.pagination import paginate
from utils.responses import success_response

router = APIRouter(prefix="/trips/{tripId}/expenses", tags=["expenses"])


def _active_member_ids(db: Session, trip_id) -> set[str]:
    return {
        str(m.user_id) for m in db.scalars(
            select(TripMember).where(TripMember.trip_id == trip_id, TripMember.status == "active")
        ).all()
    }


def _can_create_expense(db: Session, trip: Trip, user_id) -> bool:
    membership = db.get(TripMember, (trip.id, user_id))
    if membership is not None and membership.role == "admin":
        return True
    if trip.expense_permission == "all_members":
        return membership is not None and membership.status == "active"
    if trip.expense_permission == "selected_members":
        allowed = db.get(TripAllowedExpenseMember, (trip.id, user_id))
        return allowed is not None
    return False  # admin_only and non-admin caller


def _expense_response(db: Session, expense: Expense, trip_id) -> dict:
    splits = db.scalars(select(ExpenseSplit).where(ExpenseSplit.expense_id == expense.id)).all()
    return ExpenseResponse(
        id=str(expense.id), tripId=str(trip_id), description=expense.description, amount=float(expense.amount),
        currency=expense.currency, category=expense.category, notes=expense.notes, tags=list(expense.tags or []),
        receiptUrl=expense.receipt_url, paidBy=str(expense.paid_by), splitType=expense.split_type,
        splits=[
            {"uid": str(s.user_id), "amount": float(s.amount),
             "percentage": float(s.percentage) if s.percentage is not None else None, "shares": s.shares}
            for s in splits
        ],
        createdBy=str(expense.created_by),
        date=datetime.combine(expense.date, datetime.min.time(), tzinfo=timezone.utc),
        createdAt=expense.created_at, updatedAt=expense.updated_at,
    ).model_dump(mode="json")


def _get_expense_or_404(db: Session, trip_id, expense_id: str) -> Expense:
    try:
        expense_uuid = uuid.UUID(expense_id)
    except ValueError as exc:
        raise NotFoundError("Expense not found") from exc
    expense = db.get(Expense, expense_uuid)
    if expense is None or str(expense.trip_id) != str(trip_id):
        raise NotFoundError("Expense not found")
    return expense


def _ensure_creator_or_admin(db: Session, expense: Expense, trip: Trip, user_id) -> None:
    membership = db.get(TripMember, (trip.id, user_id))
    is_admin = membership is not None and membership.role == "admin"
    if str(expense.created_by) != str(user_id) and not is_admin:
        raise ForbiddenError("Only the expense creator or a trip admin can modify this expense")


@router.post("")
def create_expense(
    tripId: str, body: ExpenseCreateRequest, user: User = Depends(get_current_user),
    trip: Trip = Depends(require_member), db: Session = Depends(get_db),
):
    if not _can_create_expense(db, trip, user.id):
        raise ForbiddenError("You do not have permission to add expenses to this trip")

    member_ids = _active_member_ids(db, trip.id)
    if body.paidBy not in member_ids:
        raise ValidationError("paidBy must be a member of this trip")
    for split in body.splits:
        if split.uid not in member_ids:
            raise ValidationError(f"Split uid '{split.uid}' is not a member of this trip")

    resolved_splits = resolve_splits(body.amount, body.splitType, body.splits)

    expense = Expense(
        trip_id=trip.id, description=body.description, amount=body.amount, currency=body.currency,
        category=body.category, notes=body.notes, tags=body.tags, receipt_url=body.receiptUrl,
        paid_by=uuid.UUID(body.paidBy), split_type=body.splitType, date=body.date, created_by=user.id,
    )
    db.add(expense)
    db.flush()

    for split in resolved_splits:
        db.add(ExpenseSplit(
            expense_id=expense.id, user_id=uuid.UUID(split["uid"]), amount=split["amount"],
            percentage=split["percentage"], shares=split["shares"],
        ))
    db.commit()
    db.refresh(expense)

    for member_uid in member_ids:
        if member_uid == str(user.id):
            continue
        send_notification(
            db, user_id=uuid.UUID(member_uid), trip_id=trip.id, type_="expense_added",
            title="New expense added", body=f"{body.description} — {body.amount} {body.currency}",
        )

    return success_response(_expense_response(db, expense, trip.id))


@router.get("")
def list_expenses(
    tripId: str,
    trip: Trip = Depends(require_member),
    db: Session = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(default=None),
    category: str | None = Query(default=None),
    memberId: str | None = Query(default=None),
    dateFrom: datetime | None = Query(default=None),
    dateTo: datetime | None = Query(default=None),
):
    stmt = select(Expense).where(Expense.trip_id == trip.id)
    if category:
        stmt = stmt.where(Expense.category == category)
    if dateFrom:
        stmt = stmt.where(Expense.date >= dateFrom.date())
    if dateTo:
        stmt = stmt.where(Expense.date <= dateTo.date())

    items, has_more, next_cursor = paginate(db, stmt, Expense.date, limit=limit, cursor=cursor)

    if memberId:
        filtered = []
        for e in items:
            if str(e.paid_by) == memberId:
                filtered.append(e)
                continue
            splits = db.scalars(select(ExpenseSplit).where(ExpenseSplit.expense_id == e.id)).all()
            if any(str(s.user_id) == memberId for s in splits):
                filtered.append(e)
        items = filtered

    return success_response(
        [_expense_response(db, e, trip.id) for e in items], meta={"cursor": next_cursor, "hasMore": has_more}
    )


@router.get("/{expenseId}")
def get_expense(tripId: str, expenseId: str, trip: Trip = Depends(require_member), db: Session = Depends(get_db)):
    expense = _get_expense_or_404(db, trip.id, expenseId)
    return success_response(_expense_response(db, expense, trip.id))


@router.patch("/{expenseId}")
def update_expense(
    tripId: str, expenseId: str, body: ExpenseUpdateRequest, user: User = Depends(get_current_user),
    trip: Trip = Depends(require_member), db: Session = Depends(get_db),
):
    expense = _get_expense_or_404(db, trip.id, expenseId)
    _ensure_creator_or_admin(db, expense, trip, user.id)

    updates = body.model_dump(exclude_unset=True)
    member_ids = _active_member_ids(db, trip.id)

    new_amount = updates.get("amount", float(expense.amount))
    new_split_type = updates.get("splitType", expense.split_type)

    new_resolved_splits = None
    if "splits" in updates:
        for s in body.splits:
            if s.uid not in member_ids:
                raise ValidationError(f"Split uid '{s.uid}' is not a member of this trip")
        validate_splits(new_amount, new_split_type, body.splits)
        new_resolved_splits = resolve_splits(new_amount, new_split_type, body.splits)
    elif "splitType" in updates:
        raise ValidationError("Changing splitType requires resending 'splits'")
    elif "amount" in updates:
        if expense.split_type == "exact":
            raise ValidationError("Changing the amount of an exact-split expense requires resending 'splits'")
        existing_splits = db.scalars(select(ExpenseSplit).where(ExpenseSplit.expense_id == expense.id)).all()
        split_inputs = [
            SplitInput(uid=str(s.user_id), amount=float(s.amount) if expense.split_type == "exact" else None,
                       percentage=float(s.percentage) if s.percentage is not None else None, shares=s.shares)
            for s in existing_splits
        ]
        new_resolved_splits = resolve_splits(new_amount, expense.split_type, split_inputs)

    if "paidBy" in updates:
        if updates["paidBy"] not in member_ids:
            raise ValidationError("paidBy must be a member of this trip")
        expense.paid_by = uuid.UUID(updates["paidBy"])

    for field, column in (("description", "description"), ("currency", "currency"), ("category", "category"),
                           ("notes", "notes"), ("tags", "tags"), ("receiptUrl", "receipt_url")):
        if field in updates:
            setattr(expense, column, updates[field])
    if "amount" in updates:
        expense.amount = updates["amount"]
    if "splitType" in updates:
        expense.split_type = updates["splitType"]
    if "date" in updates and updates["date"] is not None:
        expense.date = updates["date"]

    if new_resolved_splits is not None:
        db.query(ExpenseSplit).filter(ExpenseSplit.expense_id == expense.id).delete()
        for split in new_resolved_splits:
            db.add(ExpenseSplit(
                expense_id=expense.id, user_id=uuid.UUID(split["uid"]), amount=split["amount"],
                percentage=split["percentage"], shares=split["shares"],
            ))

    db.commit()
    db.refresh(expense)
    return success_response(_expense_response(db, expense, trip.id))


@router.delete("/{expenseId}")
def delete_expense(
    tripId: str, expenseId: str, user: User = Depends(get_current_user),
    trip: Trip = Depends(require_member), db: Session = Depends(get_db),
):
    expense = _get_expense_or_404(db, trip.id, expenseId)
    _ensure_creator_or_admin(db, expense, trip, user.id)
    db.delete(expense)
    db.commit()
    return success_response({"id": expenseId, "deleted": True})
