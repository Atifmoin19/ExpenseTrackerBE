from datetime import date as date_type
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

SplitType = Literal["equal", "exact", "percentage", "shares"]

EPSILON = 0.01


class SplitInput(BaseModel):
    uid: str
    amount: float | None = None
    percentage: float | None = None
    shares: int | None = None

    @field_validator("shares")
    @classmethod
    def positive_shares(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("shares must be a positive integer")
        return v

    @field_validator("percentage")
    @classmethod
    def valid_percentage(cls, v: float | None) -> float | None:
        if v is not None and not (0 < v <= 100):
            raise ValueError("percentage must be between 0 and 100")
        return v


def validate_splits(amount: float, split_type: str, splits: list[SplitInput]) -> None:
    """Shared split validation used both at request-parse time (ExpenseCreateRequest)
    and by the router when a PATCH resends `splits` — raises ValueError on failure."""
    if not splits:
        raise ValueError("splits must contain at least one entry")

    uids = [s.uid for s in splits]
    if len(uids) != len(set(uids)):
        raise ValueError("duplicate uid in splits")

    if split_type == "exact":
        if any(s.amount is None for s in splits):
            raise ValueError("exact split requires 'amount' for every member")
        total = sum(abs(s.amount) for s in splits)
        if abs(total - amount) > EPSILON:
            raise ValueError(f"exact splits must sum to the expense amount ({amount}), got {total}")
    elif split_type == "percentage":
        if any(s.percentage is None for s in splits):
            raise ValueError("percentage split requires 'percentage' for every member")
        total_pct = sum(s.percentage for s in splits)
        if abs(total_pct - 100) > EPSILON:
            raise ValueError(f"percentages must sum to 100, got {total_pct}")
    elif split_type == "shares":
        if any(s.shares is None for s in splits):
            raise ValueError("shares split requires 'shares' for every member")
        if any(s.shares <= 0 for s in splits):
            raise ValueError("shares must be positive integers")
    elif split_type == "equal":
        pass
    else:
        raise ValueError(f"Unknown splitType: {split_type}")


def resolve_splits(amount: float, split_type: str, splits: list[SplitInput]) -> list[dict]:
    """Resolves each split's absolute `amount` regardless of splitType, per the
    Firestore schema contract ("amount always resolved to absolute value
    regardless of splitType"). Rounds to 2 decimals and nudges the last entry
    to absorb any rounding drift so resolved amounts always sum exactly to
    `amount`."""
    if not splits:
        return []

    resolved: list[dict] = []
    if split_type == "equal":
        share = round(amount / len(splits), 2)
        for s in splits:
            resolved.append({"uid": s.uid, "amount": share, "percentage": None, "shares": None})
    elif split_type == "exact":
        for s in splits:
            resolved.append({"uid": s.uid, "amount": round(abs(s.amount), 2), "percentage": None, "shares": None})
    elif split_type == "percentage":
        for s in splits:
            resolved.append({
                "uid": s.uid, "amount": round(amount * s.percentage / 100, 2),
                "percentage": s.percentage, "shares": None,
            })
    elif split_type == "shares":
        total_shares = sum(s.shares for s in splits)
        for s in splits:
            resolved.append({
                "uid": s.uid, "amount": round(amount * s.shares / total_shares, 2),
                "percentage": None, "shares": s.shares,
            })
    else:
        raise ValueError(f"Unknown splitType: {split_type}")

    drift = round(amount - sum(r["amount"] for r in resolved), 2)
    if abs(drift) >= 0.01:
        resolved[-1]["amount"] = round(resolved[-1]["amount"] + drift, 2)

    return resolved


class ExpenseCreateRequest(BaseModel):
    description: str = Field(min_length=1, max_length=500)
    amount: float = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    category: str | None = None
    notes: str | None = None
    tags: list[str] = Field(default_factory=list)
    receiptUrl: str | None = None
    paidBy: str
    splitType: SplitType
    splits: list[SplitInput] = Field(min_length=1)
    # Aliased import (date_type) — a field literally named `date` annotated as
    # `date | None = None` triggers a Python class-body self-shadowing bug
    # where the type name resolves to None before the assignment executes.
    date: date_type

    @field_validator("currency")
    @classmethod
    def upper_currency(cls, v: str) -> str:
        return v.upper()

    @model_validator(mode="after")
    def check_splits(self):
        try:
            validate_splits(self.amount, self.splitType, self.splits)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        return self


class ExpenseUpdateRequest(BaseModel):
    description: str | None = Field(default=None, min_length=1, max_length=500)
    amount: float | None = Field(default=None, gt=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    category: str | None = None
    notes: str | None = None
    tags: list[str] | None = None
    receiptUrl: str | None = None
    paidBy: str | None = None
    splitType: SplitType | None = None
    splits: list[SplitInput] | None = None
    date: date_type | None = None

    @field_validator("currency")
    @classmethod
    def upper_currency(cls, v: str | None) -> str | None:
        return v.upper() if v else v


class ExpenseSplitResponse(BaseModel):
    uid: str
    amount: float
    percentage: float | None = None
    shares: int | None = None


class ExpenseResponse(BaseModel):
    id: str
    tripId: str
    description: str
    amount: float
    currency: str
    category: str | None = None
    notes: str | None = None
    tags: list[str] = Field(default_factory=list)
    receiptUrl: str | None = None
    paidBy: str
    splitType: SplitType
    splits: list[ExpenseSplitResponse]
    createdBy: str
    date: datetime
    createdAt: datetime
    updatedAt: datetime
