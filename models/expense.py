"""`expenses` and `expense_splits` tables."""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base

SplitType = Enum("equal", "exact", "percentage", "shares", name="split_type", create_type=True)


class Expense(Base):
    __tablename__ = "expenses"
    __table_args__ = (
        # CONTRACT.md indexes: expenses(trip_id, date desc), expenses(trip_id, category)
        Index("ix_expenses_trip_id_date", "trip_id", "date"),
        Index("ix_expenses_trip_id_category", "trip_id", "category"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    trip_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(String, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    category: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(postgresql.ARRAY(String), nullable=False, default=list)
    receipt_url: Mapped[str | None] = mapped_column(String, nullable=True)
    paid_by: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    split_type: Mapped[str] = mapped_column(SplitType, nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ExpenseSplit(Base):
    __tablename__ = "expense_splits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    expense_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("expenses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    # Always the resolved absolute amount, regardless of split_type.
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    percentage: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    shares: Mapped[int | None] = mapped_column(Integer, nullable=True)
