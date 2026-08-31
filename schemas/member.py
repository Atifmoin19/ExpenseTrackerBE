from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr

MemberRole = Literal["admin", "member"]
MemberStatus = Literal["active", "removed"]


class MemberAddRequest(BaseModel):
    email: EmailStr


class MemberRoleUpdateRequest(BaseModel):
    role: MemberRole


class MemberResponse(BaseModel):
    uid: str
    role: MemberRole
    displayName: str | None = None
    photoUrl: str | None = None
    joinedAt: datetime
    status: MemberStatus
