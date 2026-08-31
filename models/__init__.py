"""SQLAlchemy ORM models — one module per table (or closely related table
pair), mirroring CONTRACT.md's "Postgres schema" section exactly.

Every model is imported here so `models.base.Base.metadata` is fully
populated for Alembic's autogenerate (`alembic/env.py` imports this package).
"""
from models.base import Base
from models.expense import Expense, ExpenseSplit
from models.invite import Invite, InviteUse
from models.member import TripAllowedExpenseMember, TripMember
from models.notification import Notification
from models.otp import OtpCode
from models.push_subscription import PushSubscription
from models.refresh_token import RefreshToken
from models.settlement import Settlement
from models.trip import Trip
from models.user import User

__all__ = [
    "Base",
    "User",
    "OtpCode",
    "RefreshToken",
    "PushSubscription",
    "Trip",
    "TripMember",
    "TripAllowedExpenseMember",
    "Expense",
    "ExpenseSplit",
    "Settlement",
    "Invite",
    "InviteUse",
    "Notification",
]
