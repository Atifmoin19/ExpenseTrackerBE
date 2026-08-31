"""`trip_members` and `trip_allowed_expense_members` tables.

`trip_members` deliberately does NOT denormalize display_name/photo_url —
CONTRACT.md notes a Postgres join to `users` is cheap, unlike the
Firestore-era reason to denormalize."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, func
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base

MemberRole = Enum("admin", "member", name="member_role", create_type=True)
MemberStatus = Enum("active", "removed", name="member_status", create_type=True)


class TripMember(Base):
    __tablename__ = "trip_members"

    trip_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[str] = mapped_column(MemberRole, nullable=False, default="member")
    status: Mapped[str] = mapped_column(MemberStatus, nullable=False, default="active")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TripAllowedExpenseMember(Base):
    """Only populated / consulted when trips.expense_permission = 'selected_members'."""

    __tablename__ = "trip_allowed_expense_members"

    trip_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
