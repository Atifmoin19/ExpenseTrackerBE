from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

SettlementMethod = Literal["cash", "upi", "bank"]


class SettlementCreateRequest(BaseModel):
    fromUid: str
    toUid: str
    amount: float = Field(gt=0)
    method: SettlementMethod
    note: str | None = None

    @model_validator(mode="after")
    def validate_parties(self):
        if self.fromUid == self.toUid:
            raise ValueError("fromUid and toUid must be different members")
        return self


class SettlementResponse(BaseModel):
    id: str
    tripId: str
    fromUid: str
    toUid: str
    amount: float
    method: SettlementMethod
    note: str | None = None
    settledBy: str
    status: Literal["completed"]
    createdAt: datetime


class SuggestedSettlement(BaseModel):
    fromUid: str
    toUid: str
    amount: float
