""""Try the demo" sandbox: creates a throwaway demo user with one seeded trip
(3 fictional members, a spread of expenses covering every split type, one
settlement) and purges expired demo users with all their data.

Every user created here, including the fictional members, is flagged
`is_demo` with the same `demo_expires_at`, so one purge clears the lot.
"""
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from core.config import settings
from models.expense import Expense, ExpenseSplit
from models.invite import Invite
from models.member import TripMember
from models.settlement import Settlement
from models.trip import Trip
from models.user import User
from schemas.expense import SplitInput, resolve_splits

DEMO_EMAIL_DOMAIN = "demo.invalid"  # RFC 2606: never deliverable


def purge_expired_demo_users(db: Session, now: datetime | None = None) -> int:
    """Deletes demo users whose sandbox has expired, plus everything they own
    or appear in. Returns the number of users removed."""
    now = now or datetime.now(timezone.utc)
    ids = list(db.scalars(
        select(User.id).where(User.is_demo.is_(True), User.demo_expires_at <= now)
    ).all())
    if not ids:
        return 0

    # Trips they created cascade to members, expenses (+splits), settlements,
    # invites and notifications at the database level.
    db.execute(delete(Trip).where(Trip.created_by.in_(ids)))
    # Anything left that references them without ON DELETE CASCADE.
    expense_ids = select(Expense.id).where(or_(Expense.paid_by.in_(ids), Expense.created_by.in_(ids)))
    db.execute(delete(ExpenseSplit).where(
        or_(ExpenseSplit.user_id.in_(ids), ExpenseSplit.expense_id.in_(expense_ids))
    ))
    db.execute(delete(Expense).where(or_(Expense.paid_by.in_(ids), Expense.created_by.in_(ids))))
    db.execute(delete(Settlement).where(or_(
        Settlement.from_user_id.in_(ids), Settlement.to_user_id.in_(ids), Settlement.settled_by.in_(ids),
    )))
    db.execute(delete(Invite).where(Invite.created_by.in_(ids)))
    db.execute(delete(User).where(User.id.in_(ids)))
    db.commit()
    return len(ids)


def live_demo_session_count(db: Session, now: datetime | None = None) -> int:
    """A sandbox is one demo owner, i.e. a live demo user that created a trip
    (the fictional members never create trips)."""
    now = now or datetime.now(timezone.utc)
    return db.scalar(
        select(func.count(func.distinct(Trip.created_by)))
        .join(User, User.id == Trip.created_by)
        .where(User.is_demo.is_(True), User.demo_expires_at > now)
    ) or 0


def _demo_user(tag: str, slug: str, name: str, expires_at: datetime) -> User:
    return User(
        email=f"demo-{tag}-{slug}@{DEMO_EMAIL_DOMAIN}", display_name=name,
        is_demo=True, demo_expires_at=expires_at, is_platform_admin=False,
    )


# (description, amount, category, payer index, split type, split spec, days after start)
# Payer/split indexes: 0 = the demo user, 1-3 = fictional members.
# Split spec: None = equal across everyone; otherwise {member index: value}.
_SEED_EXPENSES = [
    ("Flight tickets", 18400, "Transport", 0, "equal", None, 0),
    ("Beach villa (3 nights)", 21000, "Lodging", 1, "shares", {0: 1, 1: 2, 2: 1, 3: 1}, 0),
    ("Airport cab", 1600, "Transport", 2, "equal", None, 0),
    ("Welcome dinner", 4200, "Food & Drink", 0, "percentage", {0: 25, 1: 25, 2: 30, 3: 20}, 0),
    ("Groceries for the villa", 2350, "Groceries", 3, "equal", None, 1),
    ("Scuba diving", 9000, "Activities", 1, "exact", {0: 3000, 1: 3000, 3: 3000}, 1),
    ("Scooter rentals", 2400, "Transport", 0, "equal", None, 1),
    ("Beach shack lunch", 1850, "Food & Drink", 2, "equal", None, 1),
    ("Spice market haul", 3100, "Shopping", 2, "exact", {0: 1200, 2: 1900}, 2),
    ("Sunset cruise", 4800, "Activities", 3, "shares", {0: 1, 1: 1, 2: 2, 3: 2}, 2),
    ("Mobile data packs", 800, "Utilities", 1, "equal", None, 2),
    ("Seafood feast", 5600, "Food & Drink", 0, "percentage", {0: 30, 1: 30, 2: 20, 3: 20}, 2),
    ("Souvenirs", 1500, "Other", 3, "exact", {1: 500, 3: 1000}, 3),
]


def create_demo_sandbox(db: Session, now: datetime | None = None) -> User:
    now = now or datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=settings.DEMO_TTL_HOURS)
    tag = uuid.uuid4().hex[:10]

    owner = _demo_user(tag, "you", "Demo Traveller", expires_at)
    friends = [
        _demo_user(tag, "aarav", "Aarav Mehta", expires_at),
        _demo_user(tag, "meera", "Meera Iyer", expires_at),
        _demo_user(tag, "kabir", "Kabir Singh", expires_at),
    ]
    people = [owner, *friends]
    db.add_all(people)
    db.flush()

    start = date.today() - timedelta(days=10)
    trip = Trip(
        name="Goa Long Weekend", description="A sample trip to explore. Everything here is fictional.",
        start_date=start, end_date=start + timedelta(days=3), currency="INR",
        created_by=owner.id, expense_permission="all_members", status="active",
    )
    db.add(trip)
    db.flush()
    db.add(TripMember(trip_id=trip.id, user_id=owner.id, role="admin", status="active"))
    for friend in friends:
        db.add(TripMember(trip_id=trip.id, user_id=friend.id, role="member", status="active"))

    for description, amount, category, payer, split_type, spec, day in _SEED_EXPENSES:
        if spec is None:
            spec = {i: None for i in range(len(people))}
        field = {"exact": "amount", "percentage": "percentage", "shares": "shares"}.get(split_type)
        inputs = [
            SplitInput(uid=str(people[i].id), **({field: value} if field else {}))
            for i, value in spec.items()
        ]
        expense = Expense(
            trip_id=trip.id, description=description, amount=amount, currency="INR", category=category,
            tags=[], paid_by=people[payer].id, split_type=split_type, date=start + timedelta(days=day),
            created_by=owner.id,
        )
        db.add(expense)
        db.flush()
        for split in resolve_splits(float(amount), split_type, inputs):
            db.add(ExpenseSplit(
                expense_id=expense.id, user_id=uuid.UUID(split["uid"]), amount=split["amount"],
                percentage=split["percentage"], shares=split["shares"],
            ))

    db.add(Settlement(
        trip_id=trip.id, from_user_id=friends[2].id, to_user_id=owner.id, amount=1500,
        method="upi", note="Part payment for flights", settled_by=friends[2].id, status="completed",
    ))
    db.commit()
    db.refresh(owner)
    return owner
