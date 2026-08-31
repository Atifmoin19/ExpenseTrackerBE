"""Presigned-URL uploads to Neon Object Storage (S3-compatible), per
CONTRACT.md's "File uploads" section.

- `key = f"{kind}s/{userId}/{uuid4()}-{filename}"`
- Presigned PUT for upload, presigned GET for view (bucket is private).
- 5MB max, image content-types only — validated server-side before presigning.
- Graceful failure (not a crash) if the bucket doesn't exist yet — the app
  still boots, only the upload endpoints 503 until it's created.
"""
import logging
import uuid
from typing import Literal

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from core.config import settings
from utils.exceptions import ServiceUnavailableError, ValidationError

logger = logging.getLogger("expense_tracker.storage")

MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5MB
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
UPLOAD_URL_TTL_SECONDS = 300
VIEW_URL_TTL_SECONDS = 300

UploadKind = Literal["receipt", "avatar"]

_client = None


def is_configured() -> bool:
    return bool(settings.AWS_ENDPOINT_URL_S3 and settings.S3_BUCKET_NAME)


def _get_client():
    global _client
    if _client is None:
        if not is_configured():
            raise ServiceUnavailableError("Object storage is not configured on this server")
        _client = boto3.client(
            "s3",
            endpoint_url=settings.AWS_ENDPOINT_URL_S3,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION or None,
            config=Config(signature_version="s3v4"),
        )
    return _client


def validate_content_type(content_type: str) -> None:
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise ValidationError(
            f"Unsupported contentType '{content_type}'. Allowed: {', '.join(sorted(ALLOWED_CONTENT_TYPES))}"
        )


def build_key(*, kind: UploadKind, user_id: str, filename: str) -> str:
    safe_name = filename.strip().replace("/", "_").replace("\\", "_") or "file"
    return f"{kind}s/{user_id}/{uuid.uuid4()}-{safe_name}"


def presign_upload(*, kind: UploadKind, user_id: str, filename: str, content_type: str) -> dict:
    """Returns {uploadUrl, fileUrl, key}. Raises ServiceUnavailableError if the
    bucket isn't configured/doesn't exist yet, ValidationError for a bad
    content type."""
    validate_content_type(content_type)
    key = build_key(kind=kind, user_id=user_id, filename=filename)
    client = _get_client()

    try:
        upload_url = client.generate_presigned_url(
            "put_object",
            Params={"Bucket": settings.S3_BUCKET_NAME, "Key": key, "ContentType": content_type},
            ExpiresIn=UPLOAD_URL_TTL_SECONDS,
        )
    except ClientError as exc:
        logger.error("Failed to presign upload URL (bucket=%s): %s", settings.S3_BUCKET_NAME, exc)
        raise ServiceUnavailableError(
            f"Object storage bucket '{settings.S3_BUCKET_NAME}' is not reachable — "
            "has it been created in the Neon console yet? See Backend/README.md."
        ) from exc

    return {"uploadUrl": upload_url, "fileUrl": key, "key": key}


def presign_view(key: str) -> str:
    """Short-lived presigned GET URL for a stored object key."""
    client = _get_client()
    try:
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.S3_BUCKET_NAME, "Key": key},
            ExpiresIn=VIEW_URL_TTL_SECONDS,
        )
    except ClientError as exc:
        logger.error("Failed to presign view URL for key=%s: %s", key, exc)
        raise ServiceUnavailableError("Object storage is currently unreachable") from exc
