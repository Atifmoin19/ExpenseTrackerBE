"""Opaque cursor encode/decode + a generic SQLAlchemy pagination helper.

A cursor encodes the last page's sort-field value (str, number, or datetime)
so the next page can filter strictly past it. datetimes are tagged so they
decode back into real `datetime` objects.
"""
import base64
import json
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Select
from sqlalchemy.orm import Session


def encode_cursor(value: Any) -> str:
    if isinstance(value, datetime):
        payload = {"t": "dt", "v": value.isoformat()}
    else:
        payload = {"t": "raw", "v": value}
    raw = json.dumps(payload, default=str).encode()
    return base64.urlsafe_b64encode(raw).decode()


def decode_cursor(cursor: Optional[str]) -> Any:
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode())
        payload = json.loads(raw)
    except Exception as exc:
        raise ValueError("Invalid pagination cursor") from exc
    if payload.get("t") == "dt":
        return datetime.fromisoformat(payload["v"])
    return payload.get("v")


def paginate(
    db: Session,
    stmt: Select,
    order_column,
    *,
    limit: int,
    cursor: Optional[str] = None,
    descending: bool = True,
) -> tuple[list, bool, Optional[str]]:
    """Applies opaque-cursor pagination to a SQLAlchemy `select()` statement,
    ordered by `order_column`. Returns (items, has_more, next_cursor)."""
    cursor_value = decode_cursor(cursor)
    if cursor_value is not None:
        stmt = stmt.where(order_column < cursor_value if descending else order_column > cursor_value)
    stmt = stmt.order_by(order_column.desc() if descending else order_column.asc())

    rows = list(db.execute(stmt.limit(limit + 1)).scalars().all())
    has_more = len(rows) > limit
    rows = rows[:limit]

    next_cursor = None
    if has_more and rows:
        next_cursor = encode_cursor(getattr(rows[-1], order_column.key))

    return rows, has_more, next_cursor
