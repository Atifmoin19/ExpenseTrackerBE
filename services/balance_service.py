"""Computes each member's net balance from a trip's expenses + settlements.

net balance = sum(amounts they paid) - sum(amounts they owe per expense splits)
              + sum(settlements they paid out) - sum(settlements they received)

A positive balance means the member is a net creditor (is owed money overall);
negative means they are a net debtor (owe money overall).

`compute_balances` itself stays a pure function over plain dicts (DB-agnostic,
independently unit-testable) — only `load_trip_balances` below knows about
SQLAlchemy, sourcing the underlying data via a SQL query instead of a
Firestore read.
"""
import uuid

from sqlalchemy.orm import Session

from models.expense import Expense, ExpenseSplit
from models.settlement import Settlement


def compute_balances(expenses: list[dict], settlements: list[dict], member_ids: list[str]) -> dict[str, float]:
    balances: dict[str, float] = {uid: 0.0 for uid in member_ids}

    for expense in expenses:
        paid_by = expense.get("paidBy")
        amount = float(expense.get("amount", 0) or 0)
        if paid_by in balances:
            balances[paid_by] += amount
        for split in expense.get("splits", []) or []:
            uid = split.get("uid")
            owed = float(split.get("amount", 0) or 0)
            if uid in balances:
                balances[uid] -= owed

    for settlement in settlements:
        if settlement.get("status") != "completed":
            continue
        from_uid = settlement.get("fromUid")
        to_uid = settlement.get("toUid")
        amount = float(settlement.get("amount", 0) or 0)
        # from_uid already paid to_uid this amount outside the expense ledger:
        # it reduces from_uid's debt (credits them) and reduces to_uid's credit.
        if from_uid in balances:
            balances[from_uid] += amount
        if to_uid in balances:
            balances[to_uid] -= amount

    return {uid: round(bal, 2) for uid, bal in balances.items()}


def load_trip_balances(db: Session, trip_id: uuid.UUID, member_ids: list[uuid.UUID]) -> dict[str, float]:
    """Loads a trip's expenses+splits and settlements from Postgres and
    returns compute_balances' result, keyed by string uid (matching the
    dashboard/settlement schemas, which serialize uids as strings)."""
    expenses_rows = db.query(Expense).filter(Expense.trip_id == trip_id).all()
    expense_ids = [e.id for e in expenses_rows]
    splits_by_expense: dict[uuid.UUID, list[ExpenseSplit]] = {}
    if expense_ids:
        for split in db.query(ExpenseSplit).filter(ExpenseSplit.expense_id.in_(expense_ids)).all():
            splits_by_expense.setdefault(split.expense_id, []).append(split)

    expenses = [
        {
            "paidBy": str(e.paid_by),
            "amount": float(e.amount),
            "splits": [
                {"uid": str(s.user_id), "amount": float(s.amount)}
                for s in splits_by_expense.get(e.id, [])
            ],
        }
        for e in expenses_rows
    ]

    settlements = [
        {
            "fromUid": str(s.from_user_id),
            "toUid": str(s.to_user_id),
            "amount": float(s.amount),
            "status": s.status,
        }
        for s in db.query(Settlement).filter(Settlement.trip_id == trip_id).all()
    ]

    return compute_balances(expenses, settlements, [str(m) for m in member_ids])
