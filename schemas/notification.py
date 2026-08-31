from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class NotificationResponse(BaseModel):
    id: str
    userId: str
    tripId: str | None = None
    type: str
    title: str
    body: str
    data: dict[str, Any] | None = None
    read: bool
    createdAt: datetime


class PushSubscriptionKeys(BaseModel):
    p256dh: str = Field(min_length=1)
    auth: str = Field(min_length=1)


class RegisterDeviceRequest(BaseModel):
    """Web Push subscription shape — `PushSubscription.toJSON()` from the
    frontend's service worker. Replaces the old `{fcmToken}` shape."""
    endpoint: str = Field(min_length=1)
    keys: PushSubscriptionKeys
