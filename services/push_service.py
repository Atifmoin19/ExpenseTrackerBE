"""Fires app notifications: writes a `notifications` row and best-effort
pushes via Web Push (`pywebpush`) to every stored `push_subscriptions` row
for the target user.

Wired into routers on: member added an expense, member settled a payment,
new member joined a trip. Never raises — a notification failure should never
fail the request that triggered it.
"""
import json
import logging
from typing import Any, Optional

from pywebpush import WebPushException, webpush
from sqlalchemy.orm import Session

from core.config import settings
from models.notification import Notification
from models.push_subscription import PushSubscription

logger = logging.getLogger("expense_tracker.push")

VAPID_CLAIMS = {"sub": settings.VAPID_SUBJECT}


def is_configured() -> bool:
    return bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY)


def send_notification(
    db: Session,
    *,
    user_id,
    trip_id,
    type_: str,
    title: str,
    body: str,
    data: Optional[dict[str, Any]] = None,
) -> None:
    """Persists the notification row, then best-effort pushes it. Commits its
    own transaction so a push failure never rolls back the caller's work."""
    notification = Notification(
        user_id=user_id, trip_id=trip_id, type=type_, title=title, body=body, data=data or {},
    )
    try:
        db.add(notification)
        db.commit()
    except Exception:
        logger.exception("Failed to write notification row for user_id=%s", user_id)
        db.rollback()
        return

    if not is_configured():
        return

    subscriptions = db.query(PushSubscription).filter(PushSubscription.user_id == user_id).all()
    if not subscriptions:
        return

    payload = json.dumps({"title": title, "body": body, "type": type_, "data": data or {}})
    stale_ids: list[int] = []

    for sub in subscriptions:
        subscription_info = {
            "endpoint": sub.endpoint,
            "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
        }
        try:
            webpush(
                subscription_info=subscription_info,
                data=payload,
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims=dict(VAPID_CLAIMS),
            )
        except WebPushException as exc:
            status_code = getattr(exc.response, "status_code", None)
            if status_code in (404, 410):
                stale_ids.append(sub.id)
            else:
                logger.warning("Push failed for subscription id=%s: %s", sub.id, exc)
        except Exception:
            logger.exception("Unexpected error sending push to subscription id=%s", sub.id)

    if stale_ids:
        try:
            db.query(PushSubscription).filter(PushSubscription.id.in_(stale_ids)).delete(
                synchronize_session=False
            )
            db.commit()
        except Exception:
            logger.exception("Failed to prune stale push subscriptions %s", stale_ids)
            db.rollback()
