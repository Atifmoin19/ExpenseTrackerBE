from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ExpensePermission = Literal["admin_only", "all_members", "selected_members"]
TripStatus = Literal["active", "archived"]


class TripCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    startDate: date
    endDate: date
    currency: str = Field(min_length=3, max_length=3, description="ISO 4217, e.g. INR")

    @field_validator("currency")
    @classmethod
    def upper_currency(cls, v: str) -> str:
        return v.upper()

    @field_validator("endDate")
    @classmethod
    def end_after_start(cls, v: date, info) -> date:
        start = info.data.get("startDate")
        if start and v < start:
            raise ValueError("endDate must be on or after startDate")
        return v


class TripUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    startDate: date | None = None
    endDate: date | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    status: TripStatus | None = None

    @field_validator("currency")
    @classmethod
    def upper_currency(cls, v: str | None) -> str | None:
        return v.upper() if v else v


class TripSettingsUpdateRequest(BaseModel):
    expensePermission: ExpensePermission
    allowedMemberIds: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_allowed_members(self):
        if self.expensePermission == "selected_members" and not self.allowedMemberIds:
            raise ValueError("allowedMemberIds must be non-empty when expensePermission is 'selected_members'")
        return self


class TripResponse(BaseModel):
    id: str
    name: str
    description: str | None = None
    startDate: datetime
    endDate: datetime
    currency: str
    createdBy: str
    # Convenience fields (not columns on `trips` — computed from trip_members /
    # trip_allowed_expense_members) kept for continuity with the pre-v2 API shape.
    adminIds: list[str] = Field(default_factory=list)
    memberIds: list[str] = Field(default_factory=list)
    expensePermission: ExpensePermission
    allowedMemberIds: list[str] = Field(default_factory=list)
    status: TripStatus
    createdAt: datetime
    updatedAt: datetime
