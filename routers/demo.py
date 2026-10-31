"""POST /auth/demo — "Try the demo" sandbox login. Only mounted behaviour when
DEMO_MODE_ENABLED is true (404 otherwise). Each call purges expired demo
users first, then creates a fresh seeded sandbox and returns a normal token
pair."""
import time
from collections import defaultdict
from threading import Lock

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from core.config import settings
from core.deps import get_db
from routers.auth import _issue_token_pair, _user_response
from schemas.auth import AuthResponse, UserResponse
from services import demo_service
from utils.exceptions import AppError, NotFoundError
from utils.responses import success_response

router = APIRouter(prefix="/auth", tags=["auth"])

_WINDOW_SECONDS = 3600
# In-memory per-IP sliding window, same single-instance caveat as
# utils/rate_limit.py.
_hits: dict[str, list[float]] = defaultdict(list)
_lock = Lock()


def reset_rate_limit() -> None:
    with _lock:
        _hits.clear()


def _check_rate_limit(ip: str) -> None:
    now = time.monotonic()
    with _lock:
        hits = _hits[ip]
        while hits and hits[0] < now - _WINDOW_SECONDS:
            hits.pop(0)
        if len(hits) >= settings.DEMO_RATE_LIMIT_PER_HOUR:
            raise AppError("rate_limited", "Too many demo sessions from this network. Try again later.", 429)
        hits.append(now)


@router.post("/demo")
def start_demo(request: Request, db: Session = Depends(get_db)):
    if not settings.DEMO_MODE_ENABLED:
        raise NotFoundError("Not found")

    _check_rate_limit(request.client.host if request.client else "unknown")
    demo_service.purge_expired_demo_users(db)
    if demo_service.live_demo_session_count(db) >= settings.DEMO_MAX_SESSIONS:
        raise AppError("demo_capacity", "The demo is busy right now. Please try again later.", 429)

    user = demo_service.create_demo_sandbox(db)
    tokens = _issue_token_pair(db, user)
    return success_response(AuthResponse(
        accessToken=tokens.accessToken, refreshToken=tokens.refreshToken, user=UserResponse(**_user_response(user)),
    ).model_dump(mode="json"))
