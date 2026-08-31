from pydantic import BaseModel


class MemberBalance(BaseModel):
    uid: str
    name: str
    net: float


class DashboardSummaryResponse(BaseModel):
    totalExpense: float
    yourExpense: float
    youOwe: float
    youGet: float
    memberBalances: list[MemberBalance]


class CategoryBreakdown(BaseModel):
    category: str
    amount: float


class MemberBreakdown(BaseModel):
    uid: str
    name: str
    amount: float


class TimelinePoint(BaseModel):
    date: str
    amount: float


class DashboardChartsResponse(BaseModel):
    byCategory: list[CategoryBreakdown]
    byMember: list[MemberBreakdown]
    timeline: list[TimelinePoint]


class TimelineActivity(BaseModel):
    """Activity-feed item for GET /trips/{tripId}/timeline. CONTRACT.md specifies
    only "Paginated activity feed" without an exact item shape, so this is a
    reasonable superset covering both expense and settlement events."""
    id: str
    type: str
    tripId: str
    actorUid: str
    actorName: str
    summary: str
    amount: float | None = None
    createdAt: str
