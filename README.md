# Expense Tracker — Backend

FastAPI backend for the Splitwise-style trip expense splitter. **v2**:
Postgres (Neon-hosted) via SQLAlchemy, backend-owned JWT auth (email OTP via
Resend + Google Identity Services token verification), Web Push/VAPID, and
presigned-URL uploads to Neon Object Storage. Firebase/Firestore/FCM have
been fully removed — see `/Users/atifmoin/ExpenseTracker/CONTRACT.md` (v2),
which this backend is built against exactly; do not diverge field names or
endpoint paths from that doc without updating it too (the frontend is built
against the same contract, in parallel).

## Stack

- FastAPI + Pydantic v2, Python 3.11+
- SQLAlchemy 2.0 (sync, `psycopg2`) + Alembic — Postgres (Neon)
- `PyJWT` (access tokens) + opaque hashed refresh tokens — no Firebase Auth
- `httpx` — OTP email delivery via EmailJS's REST API (routes through a connected Gmail account, no domain verification needed)
- `google-auth` — verifies Google Identity Services ID tokens
- `boto3` — presigned S3-compatible URLs against Neon Object Storage
- `pywebpush` — Web Push notifications (VAPID)
- Deployed to Render.com (Docker)

## Running locally against the real Neon DB

```bash
cd Backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in real values, see "Getting real credentials" below
alembic upgrade head   # creates every table in CONTRACT.md's Postgres schema
uvicorn main:app --reload --port 8000
```

`DATABASE_URL` is a real, already-provisioned Neon Postgres connection
string — there is no local/SQLite fallback. `JWT_SECRET`, `VAPID_PUBLIC_KEY`/
`VAPID_PRIVATE_KEY`, and the `AWS_*`/`S3_BUCKET_NAME` values are also
expected to be real. `EMAILJS_SERVICE_ID`/`EMAILJS_TEMPLATE_ID`/
`EMAILJS_PUBLIC_KEY`/`EMAILJS_PRIVATE_KEY`, `GOOGLE_CLIENT_ID`, and
`GOOGLE_CLIENT_SECRET` may legitimately be blank in development — see
"Degraded-mode behavior" below for what that changes.

Interactive API docs: `http://localhost:8000/docs`.

## Running Alembic migrations

```bash
# apply all migrations (creates/updates every table)
alembic upgrade head

# after changing a model in models/*.py, generate a new migration:
alembic revision --autogenerate -m "describe the change"
alembic upgrade head

# roll back one migration:
alembic downgrade -1
```

`alembic/env.py` reads `DATABASE_URL` from `core/config.py` (i.e. from
`Backend/.env` / the environment) at runtime — the `sqlalchemy.url` line in
`alembic.ini` is an unused placeholder, never the real connection string.
Every model in `models/*.py` is imported by `models/__init__.py`, which
`alembic/env.py` imports so `--autogenerate` sees the full schema.

## Degraded-mode behavior (blank EmailJS vars / `GOOGLE_CLIENT_ID`)

- **OTP email (EmailJS vars unset):** `POST /auth/otp/request` still
  works — the 6-digit code is logged to the server console
  (`[DEV OTP] <email> -> <code>`) and returned in the response envelope as
  `data.debugCode`, so the full OTP flow is testable locally without an
  EmailJS account. Once EmailJS is configured, `debugCode` is always
  `null` (never leak the code over the wire) — but in `ENV=development` the
  code is *still* logged to the server console with the same
  `[DEV OTP] <email> -> <code>` line, so testing against arbitrary emails
  stays possible without depending on actual email delivery.
- **Google login (`GOOGLE_CLIENT_ID` unset):** `POST /auth/google` returns a
  clean `503 service_unavailable` ("Google login is not configured on this
  server") instead of crashing.
- **Object storage bucket not yet created:** `POST /uploads/presign`
  succeeds (presigning is local, no network call), but the actual `PUT`/
  `GET` against Neon Object Storage 404s with `NoSuchBucket` until the
  bucket named by `S3_BUCKET_NAME` exists — see "Object Storage bucket"
  below. The app itself never crashes over this.

## Getting real credentials

1. **Neon Postgres** — already provisioned; `DATABASE_URL` in `.env` is
   live. To point at a different Neon project/branch, copy its pooled
   connection string from the Neon console into `DATABASE_URL`.
2. **EmailJS** (`EMAILJS_SERVICE_ID`, `EMAILJS_TEMPLATE_ID`,
   `EMAILJS_PUBLIC_KEY`, `EMAILJS_PRIVATE_KEY`) — create an account at
   [emailjs.com](https://emailjs.com), connect a Gmail account (Email
   Services page → Service ID), create a template with a `{{code}}`
   variable and a dynamic `{{to_email}}` recipient field (Template ID),
   and grab the Public Key (Account → General) and Private Key (Account →
   Security). On that same Security page, enable "Allow EmailJS API for
   non-browser applications" — without it EmailJS rejects server-to-server
   calls since it normally only expects requests from a browser on a
   registered domain. Unlike Resend, no domain verification is needed —
   EmailJS routes mail through the connected Gmail account directly, so it
   can deliver to any recipient from day one. Free tier caps at 200
   emails/month.
3. **Google Identity Services** (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`)
   — Google Cloud Console → APIs & Services → Credentials → **Create
   OAuth client ID** → Application type **Web application**. Add your
   frontend's origin(s) to "Authorized JavaScript origins". Copy the client
   ID into both `Backend/.env`'s `GOOGLE_CLIENT_ID` and the frontend's
   `VITE_GOOGLE_CLIENT_ID` (must match — the backend verifies the ID
   token's audience against `GOOGLE_CLIENT_ID`). `GOOGLE_CLIENT_SECRET`
   isn't currently used server-side (the frontend does the full GIS flow
   client-side) but is kept in `.env` for a future server-side OAuth flow,
   per CONTRACT.md.
4. **VAPID** (`VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`) — already generated
   and live in `.env`. To regenerate: `.venv/bin/python -c "from py_vapid
   import Vapid02; v = Vapid02(); v.generate_keys(); print(v.public_key,
   v.private_key)"` (or use `pywebpush`'s `vapid` CLI). The **public** key
   must be byte-for-byte identical to the frontend's
   `VITE_VAPID_PUBLIC_KEY`.
5. **Neon Object Storage** (`AWS_ENDPOINT_URL_S3`, `AWS_ACCESS_KEY_ID`,
   `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `S3_BUCKET_NAME`) — already live
   in `.env` (Neon console → Object Storage → generate S3-compatible
   credentials). **You must still create the bucket** named exactly
   `S3_BUCKET_NAME`'s value in the Neon console (Object Storage → Create
   bucket) before uploads work — see below.

## Object Storage bucket

Presigning (`POST /uploads/presign`) works immediately once
`AWS_ENDPOINT_URL_S3`/credentials/`S3_BUCKET_NAME` are set, since it's a
local signing operation with no network call. But the actual file
upload/download against Neon Object Storage will fail with `NoSuchBucket`
until the bucket exists. To create it:

1. Neon console → your project → **Object Storage**.
2. **Create bucket**, name it exactly the value of `S3_BUCKET_NAME` in
   `.env`.
3. Retry the upload — no backend restart needed.

This was verified live during development: presigning succeeded and
returned a well-formed signed URL, but the subsequent `PUT` 404'd with
`NoSuchBucket` because the bucket hadn't been created yet in this Neon
project — exactly the documented, non-crashing degraded state.

## Deploying to Render

`render.yaml` + `Dockerfile` are set up for a Docker web service:

1. Push this repo to GitHub/GitLab.
2. In Render: New → Blueprint → point at the repo (picks up `render.yaml`).
3. Set every `sync: false` env var in the Render dashboard (never committed):
   `DATABASE_URL`, `JWT_SECRET`, `EMAILJS_SERVICE_ID`, `EMAILJS_TEMPLATE_ID`,
   `EMAILJS_PUBLIC_KEY`, `EMAILJS_PRIVATE_KEY`,
   `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `VAPID_PUBLIC_KEY`,
   `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT`, `AWS_ENDPOINT_URL_S3`,
   `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`,
   `S3_BUCKET_NAME`.
4. Set `ALLOWED_ORIGINS` to the deployed frontend's origin(s), comma-separated.
5. Render's free tier doesn't support `preDeployCommand`, so the Dockerfile's
   `CMD` runs `alembic upgrade head` itself before starting uvicorn on every
   boot — idempotent against an already-migrated DB, no manual step needed.
6. Render sets `PORT` automatically; the Dockerfile's `CMD` reads it.
7. Health check path is `/health`.

## Testing

`test_e2e.py` covers the full v2 flow against the **live** Neon database
configured in `.env` (no test DB, no mocks — matches CONTRACT.md's
Postgres-backed model): OTP request/verify (works whether or not EmailJS
is configured — see "Degraded-mode behavior" above),
`/auth/me`, trip creation, adding a second member, a two-member equal-split
expense, dashboard summary balance correctness, the suggested-settlements
optimizer, recording a settlement and confirming balances zero out, invite
preview/accept, and a few auth/permission error cases. It tags every row it
creates and deletes them all in a fixture at the end of the run.

```bash
pip install -r requirements-dev.txt   # pytest + httpx, not in requirements.txt (runtime deps only)
alembic upgrade head                  # schema must already exist
pytest test_e2e.py -v
```

This was run against the real Neon DB during development (all 4 tests
passed, ~65s — most of that is real network round-trips to Postgres and, for
one login, to Resend) and its own cleanup fixture removed everything it
created. A manual `curl`-driven pass (documented in the PR/task notes) was
also run and cleaned up separately, confirming: OTP → JWT round trip,
`/auth/me`, trip creation with creator as sole admin+member, adding a second
member, a two-member split expense with correct resolved amounts, dashboard
summary/charts math, the suggested-settlements optimizer, recording a
settlement (balances correctly zeroed to 0/0 afterward), invite create/
preview/accept, refresh-token rotation (old token correctly rejected after
rotation), logout, push-subscription registration, and every degraded-mode
path (Google login 503, presigned-upload `NoSuchBucket`, wrong-OTP
`validation_error`, missing-auth `401`, non-admin `403`).

## Scaling notes

**Pagination.** All list endpoints use opaque cursor pagination
(`utils/pagination.py`'s `paginate()` helper — wraps a SQLAlchemy `select()`
with a `WHERE order_column < cursor` + `LIMIT` — used identically across
trips/expenses/settlements/notifications). The trip timeline endpoint merges
expenses+settlements in-process (simpler than the old two-source Firestore
cursor scheme, since a single SQL trip's activity volume is small enough to
sort in Python).

**Rate limiting.** `utils/rate_limit.py` adds a simple in-memory fixed-window
limiter (120 req/min per client IP by default), wired into `main.py`. It's
per-process — fine for a single Render instance, but once this scales to
multiple instances the counters won't be shared across them. Swap it for a
Redis-backed limiter at that point; the middleware interface stays the same.

**Dashboard caching.** `GET /trips/{tripId}/dashboard/summary` and
`/dashboard/charts` recompute from every expense/settlement in the trip on
every call — no caching layer yet. For a trip with a lot of expenses, add a
short-TTL cache (10–30s) keyed by `tripId`, invalidated on expense/settlement
writes for that trip.

**Push notification cleanup.** `services/push_service.py` deletes a
`push_subscriptions` row automatically on a 404/410 response from the push
service (an expired/unsubscribed browser subscription), per CONTRACT.md.

## Deviations from CONTRACT.md (and why)

CONTRACT.md doesn't pin down every implementation detail — these are the
judgment calls made to fill the gaps, none of which change a field name,
table shape, or endpoint path:

- **Trip response convenience fields.** `trips` (the table) doesn't store
  `adminIds`/`memberIds`/`allowedMemberIds` — those live in `trip_members` /
  `trip_allowed_expense_members`. `TripResponse` still returns them (computed
  via a join at read time) for continuity with the pre-v2 API shape the
  frontend already expects; a Postgres join is cheap, per CONTRACT.md's own
  note about why Firestore-era denormalization is no longer needed.
- **OTP details.** 10-minute expiry, 5 max verify attempts, and a SHA-256
  hash (not bcrypt/argon2 — a 6-digit code has too little entropy for a slow
  hash to meaningfully help, and the OTP row already expires quickly) aren't
  specified in CONTRACT.md; these are reasonable defaults.
  `otp_codes` rows are deleted immediately on successful verify (can't be
  replayed) rather than merely marked used.
- **Refresh token rotation.** Per CONTRACT.md's "rotates it (issues a new
  pair, revokes the old row)" — implemented as: look up by hash, reject if
  revoked/expired, mark the old row `revoked_at`, issue + store a new row.
- **Response envelope error codes.** `error.code` values (`not_found`,
  `forbidden`, `validation_error`, `conflict`, `service_unavailable`,
  `unauthorized`, `http_error`, `internal_error`, `rate_limited`) aren't
  specified beyond the `{code, message}` shape — unchanged from the pre-v2
  implementation's stable vocabulary in `utils/exceptions.py`.
- **Timeline activity shape.** CONTRACT.md specifies only "Paginated
  activity feed" for `GET /trips/{tripId}/timeline` without an item shape;
  `schemas/dashboard.py:TimelineActivity` defines one (`id, type, tripId,
  actorUid, actorName, summary, amount, createdAt`) covering both expense
  and settlement events — unchanged from v1.
- **Invite creation body.** CONTRACT.md doesn't specify a request body for
  `POST /trips/{tripId}/invites`; `InviteCreateRequest` adds optional
  `maxUses` and `expiresInDays` (default 7) — unchanged from v1.
- **`PATCH /trips/{tripId}/expenses/{expenseId}` split changes.** If a PATCH
  changes `amount` without resending `splits`, existing split weights are
  rescaled proportionally — except `splitType: exact`, which requires
  resending `splits` explicitly (422). Changing `splitType` itself always
  requires resending `splits`. Unchanged from v1.
- **Upload view endpoint auth.** CONTRACT.md allows either a redirect or a
  `{viewUrl}` body for `GET /uploads/{key}/view`; this implementation
  returns `{viewUrl}` in the standard envelope (simpler for the frontend to
  handle uniformly with every other endpoint) and requires auth but doesn't
  independently re-check trip membership per key — any authenticated user
  can view any key they were handed via an expense/settlement/profile
  response, which already scopes what URLs a client legitimately has.
- **`models/` vs `schemas/`.** `models/*.py` are the SQLAlchemy ORM table
  definitions (mirroring CONTRACT.md's Postgres schema section exactly);
  `schemas/*.py` are the separate Pydantic request/response models at the
  HTTP boundary — kept distinct because a few API responses add
  convenience fields (e.g. `ExpenseResponse.tripId`, `TripResponse.adminIds`)
  that aren't literal columns.

## Project layout

```text
core/       settings, SQLAlchemy engine/session, JWT+OTP security helpers, shared FastAPI dependencies
models/     SQLAlchemy ORM models — one module per table (mirrors CONTRACT.md schema exactly)
alembic/    migration environment + versions/ (first migration creates every table+index)
schemas/    request/response Pydantic models per API area
routers/    one router module per API area, mounted under /api/v1
services/   email OTP (Resend), Google ID token verify, S3 presign, Web Push, settlement optimizer, balance calc
utils/      response envelope, exceptions, pagination, rate limiting
main.py     app wiring: CORS, exception handlers, routers, /health
test_e2e.py end-to-end pytest against the real Neon DB
```
