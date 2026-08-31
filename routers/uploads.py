"""Presigned-URL uploads (receipts + avatars) to Neon Object Storage, per
CONTRACT.md's "File uploads" section."""
from fastapi import APIRouter, Depends

from core.deps import get_current_user
from models.user import User
from schemas.upload import PresignUploadRequest, PresignUploadResponse, ViewUrlResponse
from services import storage_service
from utils.responses import success_response

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post("/presign")
def presign_upload(body: PresignUploadRequest, user: User = Depends(get_current_user)):
    result = storage_service.presign_upload(
        kind=body.kind, user_id=str(user.id), filename=body.filename, content_type=body.contentType,
    )
    return success_response(PresignUploadResponse(**result).model_dump(mode="json"))


@router.get("/{key:path}/view")
def view_upload(key: str, user: User = Depends(get_current_user)):
    """Returns a short-lived presigned GET URL for a stored object key.
    Ownership/trip-membership isn't independently checkable from the key
    alone beyond auth being required — the key namespace
    (`{kind}s/{userId}/...`) already scopes receipts/avatars per-uploader;
    any authenticated user of this trip-sharing app may view a receipt whose
    URL they were handed via an expense/settlement/profile response."""
    view_url = storage_service.presign_view(key)
    return success_response(ViewUrlResponse(viewUrl=view_url).model_dump(mode="json"))
