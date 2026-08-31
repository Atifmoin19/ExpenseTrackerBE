"""Sends the OTP email via Resend's HTTP API.

When `RESEND_API_KEY` is unset (dev, no real Resend account yet), never
fail — log the OTP code clearly to stdout instead, so the auth flow is
testable end-to-end locally without a Resend account. The caller
(`routers/auth.py`) is responsible for surfacing a `debugCode` field in the
response envelope in that same situation.

Even once a real `RESEND_API_KEY` is configured, the code is still logged to
the server's own console (never returned via the API) in development — a
sandboxed Resend account can only deliver to its own verified address, so
this keeps local testing against arbitrary emails possible without real
inbox access. `DEV_OTP_LOG_PREFIX` is shared with test_e2e.py, which parses
it out of captured logs when `RESEND_API_KEY` is set (so `debugCode` isn't
available) instead of needing real email delivery.
"""
import logging

import resend

from core.config import settings

logger = logging.getLogger("expense_tracker.email")

DEV_OTP_LOG_PREFIX = "[DEV OTP]"


def is_configured() -> bool:
    return bool(settings.RESEND_API_KEY)


def send_otp_email(*, to_email: str, code: str) -> None:
    """Best-effort send. Never raises — a transient Resend outage shouldn't
    break the OTP request flow (the code is still valid/stored either way)."""
    if settings.is_development:
        logger.info("%s %s -> %s", DEV_OTP_LOG_PREFIX, to_email, code)

    if not is_configured():
        print(f"\n{DEV_OTP_LOG_PREFIX} {to_email} -> {code}\n", flush=True)
        return

    resend.api_key = settings.RESEND_API_KEY
    try:
        result = resend.Emails.send({
            "from": settings.RESEND_FROM_EMAIL,
            "to": [to_email],
            "subject": "Your Expense Tracker verification code",
            "html": (
                f"<p>Your verification code is:</p>"
                f"<h2 style='letter-spacing:4px'>{code}</h2>"
                f"<p>This code expires in 10 minutes. If you didn't request this, ignore this email.</p>"
            ),
        })
        logger.info("Resend accepted OTP email to %s (id=%s)", to_email, getattr(result, "get", lambda *_: None)("id"))
    except Exception:
        logger.exception("Failed to send OTP email to %s via Resend", to_email)
