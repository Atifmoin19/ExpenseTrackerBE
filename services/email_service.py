"""Sends the OTP email via EmailJS's REST API.

EmailJS routes mail through a connected Gmail account, so no domain
verification is needed (unlike Resend, which requires a verified domain to
deliver to arbitrary recipients). The private key doubles as the
`accessToken` that lets a server-side (non-browser) request through —
EmailJS normally only accepts requests whose Origin header matches a
registered website, and that check is bypassed for whoever holds the
private key plus the "Allow EmailJS API for non-browser applications"
account setting enabled.

When EmailJS isn't configured (local dev, no account set up yet), never
fail — log the OTP code clearly to stdout instead, so the auth flow is
testable end-to-end without sending real email. The caller
(`routers/auth.py`) is responsible for surfacing a `debugCode` field in the
response envelope in that same situation.
"""
import logging

import httpx

from core.config import settings

logger = logging.getLogger("expense_tracker.email")

DEV_OTP_LOG_PREFIX = "[DEV OTP]"

EMAILJS_SEND_URL = "https://api.emailjs.com/api/v1.0/email/send"


def is_configured() -> bool:
    return bool(
        settings.EMAILJS_SERVICE_ID
        and settings.EMAILJS_TEMPLATE_ID
        and settings.EMAILJS_PUBLIC_KEY
        and settings.EMAILJS_PRIVATE_KEY
    )


def send_otp_email(*, to_email: str, code: str) -> None:
    """Best-effort send. Never raises — a transient EmailJS outage shouldn't
    break the OTP request flow (the code is still valid/stored either way)."""
    if settings.is_development:
        logger.info("%s %s -> %s", DEV_OTP_LOG_PREFIX, to_email, code)

    if not is_configured():
        print(f"\n{DEV_OTP_LOG_PREFIX} {to_email} -> {code}\n", flush=True)
        return

    payload = {
        "service_id": settings.EMAILJS_SERVICE_ID,
        "template_id": settings.EMAILJS_TEMPLATE_ID,
        "user_id": settings.EMAILJS_PUBLIC_KEY,
        "accessToken": settings.EMAILJS_PRIVATE_KEY,
        "template_params": {
            "to_email": to_email,
            "code": code,
        },
    }
    try:
        response = httpx.post(EMAILJS_SEND_URL, json=payload, timeout=10.0)
        response.raise_for_status()
        logger.info("EmailJS accepted OTP email to %s", to_email)
    except Exception:
        logger.exception("Failed to send OTP email to %s via EmailJS", to_email)
