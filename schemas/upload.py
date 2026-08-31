from typing import Literal

from pydantic import BaseModel, Field

UploadKind = Literal["receipt", "avatar"]


class PresignUploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    contentType: str = Field(min_length=1)
    kind: UploadKind


class PresignUploadResponse(BaseModel):
    uploadUrl: str
    fileUrl: str
    key: str


class ViewUrlResponse(BaseModel):
    viewUrl: str
