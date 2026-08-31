"""Expense Tracker backend — FastAPI app: CORS, envelope exception handlers,
rate limiting, versioned routers, health check."""
import logging
import os

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.config import settings
from routers import auth, dashboard, expense, invite, member, notification, settlement, trip, uploads
from utils.exceptions import AppError
from utils.rate_limit import RateLimitMiddleware
from utils.responses import error_envelope

# Without an explicit handler, app-level `logging.getLogger(...).info(...)`
# calls (e.g. services/email_service.py's dev-mode OTP log line) are silently
# dropped by Python's root logger default (WARNING, no handler) even though
# uvicorn's own access/error logs still show — so configure it explicitly.
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

app = FastAPI(title="Expense Tracker Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# In-memory fixed-window limiter — see utils/rate_limit.py for scaling notes.
app.add_middleware(RateLimitMiddleware, limit=120, window_seconds=60)


# ── Response-envelope exception handlers ─────────────────────────────────────
@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=error_envelope(exc.code, exc.message))


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    message = errors[0]["msg"] if errors else "Validation failed"
    return JSONResponse(status_code=422, content=error_envelope("validation_error", message))


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=error_envelope("http_error", str(exc.detail)))


@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content=error_envelope("internal_error", "Internal server error"))


# ── Routers, all mounted under /api/v1 per CONTRACT.md ────────────────────────
API_PREFIX = "/api/v1"
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(trip.router, prefix=API_PREFIX)
app.include_router(member.router, prefix=API_PREFIX)
app.include_router(invite.trip_invites_router, prefix=API_PREFIX)
app.include_router(invite.invites_router, prefix=API_PREFIX)
app.include_router(expense.router, prefix=API_PREFIX)
app.include_router(dashboard.router, prefix=API_PREFIX)
app.include_router(dashboard.timeline_router, prefix=API_PREFIX)
app.include_router(settlement.router, prefix=API_PREFIX)
app.include_router(notification.router, prefix=API_PREFIX)
app.include_router(uploads.router, prefix=API_PREFIX)


@app.get("/health", tags=["health"])
def health() -> dict:
    return {"status": "ok", "env": settings.ENV}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=True)
