from datetime import datetime

from pydantic import BaseModel, Field


class InviteCreateRequest(BaseModel):
    maxUses: int | None = Field(default=None, gt=0)
    expiresInDays: int = Field(default=7, gt=0, le=365)


class InviteCreateResponse(BaseModel):
    code: str
    tripId: str
    expiresAt: datetime
    maxUses: int | None = None
    inviteUrl: str


class InvitePreviewResponse(BaseModel):
    """Public preview — deliberately excludes member identities, just counts."""
    tripId: str
    tripName: str
    startDate: datetime
    endDate: datetime
    memberCount: int
    expiresAt: datetime


class InviteAcceptResponse(BaseModel):
    tripId: str
    joined: bool
