"""Tests for the "Try the demo" sandbox (POST /api/v1/auth/demo).

Runs against the DATABASE_URL in .env like test_e2e.py. Every demo user this
module creates is expired and purged at the end.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from core.config import settings
from core.database import SessionLocal
from main import app
from models.trip import Trip
from models.user import User
from routers import demo as demo_router
from services import demo_service

client = TestClient(app)
API = "/api/v1"


@pytest.fixture(autouse=True)
def demo_enabled(monkeypatch):
    monkeypatch.setattr(settings, "DEMO_MODE_ENABLED", True)
    demo_router.reset_rate_limit()
    yield
    demo_router.reset_rate_limit()


@pytest.fixture(scope="module", autouse=True)
def _purge_created_demo_users():
    yield
    db = SessionLocal()
    try:
        for user in db.scalars(select(User).where(User.is_demo.is_(True))).all():
            user.demo_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
        demo_service.purge_expired_demo_users(db)
    finally:
        db.close()


def _start_demo():
    r = client.post(f"{API}/auth/demo")
    assert r.status_code == 200, r.text
    return r.json()["data"]


def test_demo_404_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "DEMO_MODE_ENABLED", False)
    assert client.post(f"{API}/auth/demo").status_code == 404


def test_demo_login_returns_tokens_and_seeded_data():
    data = _start_demo()
    assert data["accessToken"] and data["refreshToken"]
    assert data["user"]["isDemo"] is True
    assert data["user"]["isPlatformAdmin"] is False
    assert data["user"]["demoExpiresAt"]
    h = {"Authorization": f"Bearer {data['accessToken']}"}

    trips = client.get(f"{API}/trips", headers=h).json()["data"]
    assert len(trips) == 1
    trip_id = trips[0]["id"]

    members = client.get(f"{API}/trips/{trip_id}/members", headers=h).json()["data"]
    assert len(members) == 4  # the demo user + 3 fictional members

    expenses = client.get(f"{API}/trips/{trip_id}/expenses", params={"limit": 100}, headers=h).json()["data"]
    assert 12 <= len(expenses) <= 15
    assert {e["splitType"] for e in expenses} == {"equal", "exact", "percentage", "shares"}
    assert len({e["category"] for e in expenses}) >= 4

    settlements = client.get(f"{API}/trips/{trip_id}/settlements", headers=h).json()["data"]
    assert len(settlements) == 1


def test_expired_demo_users_are_purged_on_next_call():
    old = _start_demo()
    old_id = uuid.UUID(old["user"]["id"])
    db = SessionLocal()
    try:
        db.get(User, old_id).demo_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    finally:
        db.close()

    _start_demo()

    db = SessionLocal()
    try:
        assert db.get(User, old_id) is None
        assert db.scalars(select(Trip).where(Trip.created_by == old_id)).first() is None
    finally:
        db.close()


def test_uploads_presign_forbidden_for_demo_users():
    data = _start_demo()
    r = client.post(
        f"{API}/uploads/presign",
        json={"kind": "receipt", "filename": "r.jpg", "contentType": "image/jpeg"},
        headers={"Authorization": f"Bearer {data['accessToken']}"},
    )
    assert r.status_code == 403


def test_demo_rate_limited_per_ip(monkeypatch):
    monkeypatch.setattr(settings, "DEMO_RATE_LIMIT_PER_HOUR", 2)
    _start_demo()
    _start_demo()
    assert client.post(f"{API}/auth/demo").status_code == 429


def test_demo_capped_by_live_sandboxes(monkeypatch):
    _start_demo()
    monkeypatch.setattr(settings, "DEMO_MAX_SESSIONS", 1)
    assert client.post(f"{API}/auth/demo").status_code == 429


def test_demo_users_excluded_from_admin_analytics():
    from routers.admin import admin_stats_summary

    db = SessionLocal()
    try:
        before = admin_stats_summary(db=db)
        _start_demo()
        after = admin_stats_summary(db=db)
    finally:
        db.close()
    b, a = before["data"], after["data"]
    assert (a["totalUsers"], a["totalTrips"], a["totalExpenses"]) == (b["totalUsers"], b["totalTrips"], b["totalExpenses"])


def test_demo_user_is_never_platform_admin():
    data = _start_demo()
    r = client.get(f"{API}/admin/stats/summary", headers={"Authorization": f"Bearer {data['accessToken']}"})
    assert r.status_code == 403
