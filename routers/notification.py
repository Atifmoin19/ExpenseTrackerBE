"""Notifications — list (current user, paginated), register a Web Push
subscription, mark one read."""
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.deps import get_current_user, get_db
from models.notification import Notification
from models.push_subscription import PushSubscription
from models.user import User
from schemas.notification import NotificationResponse, RegisterDeviceRequest
from utils.exceptions import ForbiddenError, NotFoundError
from utils.pagination import paginate
from utils.responses import success_response

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _notification_response(n: Notification) -> dict:
    return NotificationResponse(
        id=str(n.id), userId=str(n.user_id), tripId=str(n.trip_id) if n.trip_id else None,
        type=n.type, title=n.title, body=n.body, data=n.data, read=n.read, createdAt=n.created_at,
    ).model_dump(mode="json")


@router.get("")
def list_notifications(
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
    limit: int = Query(20, ge=1, le=100), cursor: str | None = Query(default=None),
):
    stmt = select(Notification).where(Notification.user_id == user.id)
    items, has_more, next_cursor = paginate(db, stmt, Notification.created_at, limit=limit, cursor=cursor)
    return success_response(
        [_notification_response(n) for n in items], meta={"cursor": next_cursor, "hasMore": has_more},
    )


@router.post("/register-device")
def register_device(body: RegisterDeviceRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    existing = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint))
    if existing is not None:
        existing.user_id = user.id
        existing.p256dh = body.keys.p256dh
        existing.auth = body.keys.auth
    else:
        db.add(PushSubscription(
            user_id=user.id, endpoint=body.endpoint, p256dh=body.keys.p256dh, auth=body.keys.auth,
        ))
    db.commit()
    return success_response({"registered": True})


@router.patch("/{notificationId}/read")
def mark_notification_read(notificationId: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        notification_uuid = uuid.UUID(notificationId)
    except ValueError as exc:
        raise NotFoundError("Notification not found") from exc
    notification = db.get(Notification, notification_uuid)
    if notification is None:
        raise NotFoundError("Notification not found")
    if str(notification.user_id) != str(user.id):
        raise ForbiddenError("You cannot modify another user's notification")
    notification.read = True
    db.commit()
    db.refresh(notification)
    return success_response(_notification_response(notification))
