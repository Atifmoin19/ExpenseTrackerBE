"""End-to-end pytest covering the full v2 (Postgres + backend-owned JWT auth)
flow against the REAL Neon database configured in Backend/.env: OTP
request/verify, /auth/me, trip creation, a two-member split expense,
dashboard summary correctness, settlement creation + suggested-settlements,
invites, and basic auth error handling.

This intentionally does NOT use a test database / mocks — CONTRACT.md calls
for verifying against the live, reachable Neon Postgres instance. Every row
this test creates is tagged with a unique `+e2e-<uuid>` email/name so it's
easy to identify and prune afterwards; the `_cleanup` fixture below deletes
everything it created at the end of the run (best-effort, via SQLAlchemy).

Reading the OTP code works whether or not a real `RESEND_API_KEY` is
configured: when it's unset, the API response itself carries a `debugCode`;
when a real key IS configured (so `debugCode` stays null, per CONTRACT.md —
never leak the code over the wire once real delivery is possible), this
grabs it instead from the same dev-mode server log line
`services/email_service.py` always emits in development
(`DEV_OTP_LOG_PREFIX`), via pytest's `caplog`. Either way the test never
depends on actually receiving an email (handy since a sandboxed Resend
account can only deliver to its own verified address).

Run: `.venv/bin/pytest test_e2e.py -v` (requires a real DATABASE_URL in .env
and the schema already migrated via `alembic upgrade head`).
"""
import re
import uuid

import pytest
from fastapi.testclient import TestClient

from core.database import SessionLocal
from main import app
from models.expense import Expense
from models.member import TripMember
from models.notification import Notification
from models.settlement import Settlement
from models.trip import Trip
from models.user import User
from services.email_service import DEV_OTP_LOG_PREFIX

client = TestClient(app)
API = "/api/v1"

RUN_ID = uuid.uuid4().hex[:8]
EMAIL_1 = f"pytest-e2e-{RUN_ID}-a@example.com"
EMAIL_2 = f"pytest-e2e-{RUN_ID}-b@example.com"

_created_user_ids: list[str] = []
_created_trip_ids: list[str] = []


def _otp_login(email: str, caplog) -> dict:
    caplog.clear()
    with caplog.at_level("INFO", logger="expense_tracker.email"):
        r = client.post(f"{API}/auth/otp/request", json={"email": email})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True

    code = body["data"]["debugCode"]
    if not code:
        # RESEND_API_KEY is configured — pull the code from the dev-mode log
        # line instead (never returned over the wire in that case).
        pattern = re.escape(DEV_OTP_LOG_PREFIX) + r" " + re.escape(email) + r" -> (\d{6})"
        match = None
        for record in caplog.records:
            match = re.search(pattern, record.message)
            if match:
                break
        assert match, f"Could not find OTP code for {email} in server logs"
        code = match.group(1)

    assert code and len(code) == 6

    r = client.post(f"{API}/auth/otp/verify", json={"email": email, "code": code})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["accessToken"] and data["refreshToken"] and data["user"]["email"] == email
    _created_user_ids.append(data["user"]["id"])
    return data


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module", autouse=True)
def _cleanup():
    yield
    db = SessionLocal()
    try:
        for trip_id in _created_trip_ids:
            db.query(Notification).filter(Notification.trip_id == trip_id).delete()
            db.query(Settlement).filter(Settlement.trip_id == trip_id).delete()
            db.query(Expense).filter(Expense.trip_id == trip_id).delete()
            db.query(TripMember).filter(TripMember.trip_id == trip_id).delete()
            trip = db.get(Trip, uuid.UUID(trip_id))
            if trip is not None:
                db.delete(trip)
        db.commit()
        for user_id in _created_user_ids:
            user = db.get(User, uuid.UUID(user_id))
            if user is not None:
                db.delete(user)
        db.commit()
    finally:
        db.close()


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_full_flow(caplog):
    # OTP login for two users.
    auth1 = _otp_login(EMAIL_1, caplog)
    auth2 = _otp_login(EMAIL_2, caplog)
    h1 = _auth_headers(auth1["accessToken"])
    h2 = _auth_headers(auth2["accessToken"])
    uid1, uid2 = auth1["user"]["id"], auth2["user"]["id"]

    # /auth/me
    r = client.get(f"{API}/auth/me", headers=h1)
    assert r.status_code == 200
    assert r.json()["data"]["email"] == EMAIL_1

    # Create a trip — creator becomes admin+member.
    r = client.post(f"{API}/trips", json={
        "name": "Pytest E2E Trip", "startDate": "2026-09-01", "endDate": "2026-09-05", "currency": "INR",
    }, headers=h1)
    assert r.status_code == 200
    trip = r.json()["data"]
    trip_id = trip["id"]
    _created_trip_ids.append(trip_id)
    assert trip["adminIds"] == [uid1]

    # Add user2 as a member.
    r = client.post(f"{API}/trips/{trip_id}/members", json={"email": EMAIL_2}, headers=h1)
    assert r.status_code == 200
    assert r.json()["data"]["uid"] == uid2

    # Split expense: 600 total, equal split between the two members.
    r = client.post(f"{API}/trips/{trip_id}/expenses", json={
        "description": "Dinner", "amount": 600, "currency": "INR", "category": "food",
        "paidBy": uid1, "splitType": "equal", "splits": [{"uid": uid1}, {"uid": uid2}],
        "date": "2026-09-02",
    }, headers=h1)
    assert r.status_code == 200
    expense = r.json()["data"]
    assert expense["splits"][0]["amount"] == 300.0
    assert expense["splits"][1]["amount"] == 300.0

    # Dashboard summary reflects the split correctly for each side.
    r = client.get(f"{API}/trips/{trip_id}/dashboard/summary", headers=h1)
    summary1 = r.json()["data"]
    assert summary1["totalExpense"] == 600.0
    assert summary1["youGet"] == 300.0
    assert summary1["youOwe"] == 0.0

    r = client.get(f"{API}/trips/{trip_id}/dashboard/summary", headers=h2)
    summary2 = r.json()["data"]
    assert summary2["youOwe"] == 300.0
    assert summary2["youGet"] == 0.0

    # Suggested settlement should be exactly uid2 -> uid1, 300.
    r = client.get(f"{API}/trips/{trip_id}/settlements/suggested", headers=h1)
    suggestions = r.json()["data"]
    assert suggestions == [{"fromUid": uid2, "toUid": uid1, "amount": 300.0}]

    # Record the settlement; balances should zero out.
    r = client.post(f"{API}/trips/{trip_id}/settlements", json={
        "fromUid": uid2, "toUid": uid1, "amount": 300, "method": "upi",
    }, headers=h2)
    assert r.status_code == 200

    r = client.get(f"{API}/trips/{trip_id}/dashboard/summary", headers=h1)
    summary1_after = r.json()["data"]
    assert summary1_after["youGet"] == 0.0
    assert summary1_after["youOwe"] == 0.0

    # Invite preview/accept flow (accept is a no-op here since uid2 already joined).
    r = client.post(f"{API}/trips/{trip_id}/invites", json={}, headers=h1)
    assert r.status_code == 200
    code = r.json()["data"]["code"]

    r = client.get(f"{API}/invites/{code}")
    assert r.status_code == 200
    assert r.json()["data"]["tripName"] == "Pytest E2E Trip"

    # Non-admin can't create an invite.
    r = client.post(f"{API}/trips/{trip_id}/invites", json={}, headers=h2)
    assert r.status_code == 403


def test_auth_errors():
    r = client.get(f"{API}/auth/me")
    assert r.status_code == 401

    r = client.post(f"{API}/auth/otp/request", json={"email": f"pytest-e2e-{RUN_ID}-c@example.com"})
    assert r.status_code == 200
    r = client.post(f"{API}/auth/otp/verify", json={
        "email": f"pytest-e2e-{RUN_ID}-c@example.com", "code": "000000",
    })
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


def test_google_auth_unconfigured_returns_503():
    r = client.post(f"{API}/auth/google", json={"idToken": "fake"})
    assert r.status_code == 503
