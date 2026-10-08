from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    filename: str
    file_type: str
    file_size: int
    storage_path: str
    status: str
    error_message: str | None = None
    checksum: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DocumentCreate(BaseModel):
    filename: str = Field(min_length=1)
    file_type: str = Field(min_length=1)
    file_size: int = Field(gt=0)
    storage_path: str = Field(min_length=1)
    checksum: str = Field(min_length=1)


class DocumentDelete(BaseModel):
    document_id: str
