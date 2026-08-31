"""Standard API response envelope — `{success, data, error, meta}` per CONTRACT.md."""
from typing import Any, Optional


def success_response(data: Any = None, meta: Optional[dict] = None) -> dict:
    return {"success": True, "data": data, "error": None, "meta": meta}


def error_envelope(code: str, message: str) -> dict:
    return {"success": False, "data": None, "error": {"code": code, "message": message}, "meta": None}
