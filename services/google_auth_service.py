"""Verifies a Google ID token (from Google Identity Services, client-side)
against `GOOGLE_CLIENT_ID` using the `google-auth` package."""
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from core.config import settings
from utils.exceptions import ServiceUnavailableError, UnauthorizedError

_request = google_requests.Request()


def is_configured() -> bool:
    return bool(settings.GOOGLE_CLIENT_ID)


def verify_google_id_token(id_token: str) -> dict:
    """Returns the verified token claims (`sub`, `email`, `name`, `picture`, ...).

    Raises ServiceUnavailableError if GOOGLE_CLIENT_ID isn't configured, or
    UnauthorizedError if the token is invalid/expired/audience-mismatched.
    """
    if not is_configured():
        raise ServiceUnavailableError("Google login is not configured on this server")

    try:
        claims = google_id_token.verify_oauth2_token(id_token, _request, settings.GOOGLE_CLIENT_ID)
    except Exception as exc:
        raise UnauthorizedError("Invalid Google ID token") from exc

    if not claims.get("email"):
        raise UnauthorizedError("Google account has no email")
    return claims
