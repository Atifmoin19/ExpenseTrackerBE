"""Platform-admin analytics — mounted under `/api/v1/admin`, every endpoint
gated by `core.deps.require_platform_admin` (a whole-app "super admin" flag
on `users.is_platform_admin`, completely separate from any per-trip
`trip_members.role == 'admin'`).

Read-only, aggregate analytics for spot-checking the platform. Every query
uses SQL-side aggregation (COUNT/SUM/GROUP BY) rather than loading rows into
Python, since these numbers should stay cheap even as the platform grows.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.deps import get_db, require_platform_admin
from models.expense import Expense
from models.member import TripMember
from models.refresh_token import RefreshToken
from models.trip import Trip
from models.user import User
from schemas.admin import (
    AdminSignupsResponse,
    AdminStatsSummaryResponse,
    AdminTripSummary,
    CurrencyVolume,
    SignupBucket,
)
from utils.pagination import decode_cursor, encode_cursor
from utils.responses import success_response

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_platform_admin)])


def _active_user_count(db: Session, since: datetime) -> int:
    """Approximate "active users" — counts distinct users who had a
    refresh_tokens row *issued* since `since`. A row is created on every
    login/signup AND on every silent token rotation (POST /auth/refresh,
    which the frontend's baseQuery fires automatically off the back of any
    authenticated API call whose access token has expired) — so
    `refresh_tokens.created_at` is a reasonable proxy for "used the app
    recently" without needing a separate last-seen column. `otp_codes` was
    considered too (its created_at marks a login *attempt*), but it isn't
    FK'd to `users` and is pruned/replayed differently, so refresh_tokens is
    the cleaner signal."""
    return db.scalar(
        select(func.count(func.distinct(RefreshToken.user_id))).where(RefreshToken.created_at >= since)
    ) or 0


@router.get("/stats/summary")
def admin_stats_summary(db: Session = Depends(get_db)):
    total_users = db.scalar(select(func.count()).select_from(User)) or 0

    active_trips = db.scalar(select(func.count()).select_from(Trip).where(Trip.status == "active")) or 0
    archived_trips = db.scalar(select(func.count()).select_from(Trip).where(Trip.status == "archived")) or 0

    total_expenses = db.scalar(select(func.count()).select_from(Expense)) or 0

    volume_rows = db.execute(
        select(Expense.currency, func.coalesce(func.sum(Expense.amount), 0))
        .group_by(Expense.currency)
        .order_by(Expense.currency)
    ).all()

    now = datetime.now(timezone.utc)
    active_7d = _active_user_count(db, now - timedelta(days=7))
    active_30d = _active_user_count(db, now - timedelta(days=30))

    return success_response(AdminStatsSummaryResponse(
        totalUsers=total_users,
        activeTrips=active_trips,
        archivedTrips=archived_trips,
        totalTrips=active_trips + archived_trips,
        totalExpenses=total_expenses,
        totalVolumeByCurrency=[CurrencyVolume(currency=c, totalAmount=float(t)) for c, t in volume_rows],
        activeUsers7d=active_7d,
        activeUsers30d=active_30d,
    ).model_dump(mode="json"))


@router.get("/stats/signups")
def admin_stats_signups(
    db: Session = Depends(get_db),
    days: int = Query(30, ge=1, le=365),
    bucket: str = Query("daily", pattern="^(daily|weekly)$"),
):
    """New user signups (`users.created_at`) over the trailing `days`,
    bucketed daily or weekly via Postgres `date_trunc` (SQL-side grouping,
    not Python)."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    trunc_unit = "day" if bucket == "daily" else "week"
    period = func.date_trunc(trunc_unit, User.created_at).label("period")

    rows = db.execute(
        select(period, func.count().label("count"))
        .where(User.created_at >= since)
        .group_by(period)
        .order_by(period)
    ).all()

    series = [SignupBucket(period=p.date().isoformat(), count=c) for p, c in rows]

    return success_response(AdminSignupsResponse(bucket=bucket, days=days, series=series).model_dump(mode="json"))


@router.get("/trips")
def admin_trips(
    db: Session = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(default=None),
):
    """Paginated list of every trip on the platform (id, name, member count,
    expense count, total expense volume, created date) for spot-checking —
    member/expense aggregates are computed via grouped subqueries joined
    once, not per-trip Python loops."""
    member_counts = (
        select(TripMember.trip_id.label("trip_id"), func.count().label("member_count"))
        .where(TripMember.status == "active")
        .group_by(TripMember.trip_id)
        .subquery()
    )
    expense_agg = (
        select(
            Expense.trip_id.label("trip_id"),
            func.count().label("expense_count"),
            func.coalesce(func.sum(Expense.amount), 0).label("total_volume"),
        )
        .group_by(Expense.trip_id)
        .subquery()
    )

    stmt = (
        select(
            Trip,
            func.coalesce(member_counts.c.member_count, 0),
            func.coalesce(expense_agg.c.expense_count, 0),
            func.coalesce(expense_agg.c.total_volume, 0),
        )
        .outerjoin(member_counts, member_counts.c.trip_id == Trip.id)
        .outerjoin(expense_agg, expense_agg.c.trip_id == Trip.id)
    )

    cursor_value = decode_cursor(cursor)
    if cursor_value is not None:
        stmt = stmt.where(Trip.created_at < cursor_value)
    stmt = stmt.order_by(Trip.created_at.desc()).limit(limit + 1)

    rows = db.execute(stmt).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = encode_cursor(rows[-1][0].created_at) if has_more and rows else None

    items = [
        AdminTripSummary(
            id=str(trip.id), name=trip.name, status=trip.status, currency=trip.currency,
            memberCount=member_count, expenseCount=expense_count, totalVolume=float(total_volume),
            createdAt=trip.created_at,
        ).model_dump(mode="json")
        for trip, member_count, expense_count, total_volume in rows
    ]

    return success_response(items, meta={"cursor": next_cursor, "hasMore": has_more})
