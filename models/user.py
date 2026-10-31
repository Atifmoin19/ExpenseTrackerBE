"""`users` table — CONTRACT.md "Postgres schema" section."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, false, func
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String, nullable=True)
    # Whole-app "super admin" flag — a property of the user, checked
    # independently of any trip membership. Completely separate from
    # trip_members.role == 'admin' (which just means "admin of one specific
    # trip"). No self-serve way to set this; granted manually via
    # scripts/grant_platform_admin.py. See core/deps.py:require_platform_admin
    # and routers/admin.py.
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    # Throwaway "Try the demo" accounts (see services/demo_service.py). Purged
    # with all their data once demo_expires_at passes; never platform admins.
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    demo_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
