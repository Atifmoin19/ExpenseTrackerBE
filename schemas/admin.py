"""Response schemas for the platform-admin analytics API (`routers/admin.py`,
mounted under `/api/v1/admin`, gated by `core.deps.require_platform_admin`).

Read-only analytics — nothing here is user-facing to a non-platform-admin.
"""
from datetime import datetime

from pydantic import BaseModel


class CurrencyVolume(BaseModel):
    currency: str
    totalAmount: float


class AdminStatsSummaryResponse(BaseModel):
    totalUsers: int
    activeTrips: int
    archivedTrips: int
    totalTrips: int
    totalExpenses: int
    totalVolumeByCurrency: list[CurrencyVolume]
    # Approximate — a user counts as "active" if a refresh_tokens row for
    # them was issued (login, signup, or a token-rotation from any
    # authenticated API call) within the window. See routers/admin.py for
    # why this is the best available proxy given the current schema.
    activeUsers7d: int
    activeUsers30d: int


class SignupBucket(BaseModel):
    period: str  # ISO date — the bucket's start (day or week)
    count: int


class AdminSignupsResponse(BaseModel):
    bucket: str  # "daily" | "weekly"
    days: int
    series: list[SignupBucket]


class AdminTripSummary(BaseModel):
    id: str
    name: str
    status: str
    currency: str
    memberCount: int
    expenseCount: int
    totalVolume: float
    createdAt: datetime
