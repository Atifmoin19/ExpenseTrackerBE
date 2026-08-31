"""Simple in-memory fixed-window rate-limit middleware.

Keyed by client IP, one counter window per (ip). This is fine for a single
Render instance but the counters live in process memory, so they are *not*
shared across multiple instances/dynos — once this service scales horizontally,
swap this for a Redis-backed limiter (e.g. a small Lua script against Redis,
or a library like `slowapi` configured with a Redis backend) so all instances
share one view of request counts. See Backend/README.md "Scaling notes".
"""
import time
from collections import defaultdict
from threading import Lock

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from utils.responses import error_envelope


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limit: int = 120, window_seconds: int = 60) -> None:
        super().__init__(app)
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        window_start = now - self.window_seconds

        with self._lock:
            hits = self._hits[client_ip]
            while hits and hits[0] < window_start:
                hits.pop(0)
            if len(hits) >= self.limit:
                return JSONResponse(
                    status_code=429,
                    content=error_envelope("rate_limited", "Too many requests — please slow down."),
                )
            hits.append(now)

        return await call_next(request)
