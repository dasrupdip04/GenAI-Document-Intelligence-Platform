from __future__ import annotations

import asyncio
from uuid import uuid4
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.core.config import get_settings
from app.core.exceptions import FileTooLargeError
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.models.stage2 import IngestionJob
from app.repositories.document_repository import DocumentRepository
from app.schemas.document import DocumentRead
from app.services.document_service import DocumentService

router = APIRouter(prefix='/api/v1/documents', tags=['documents'])


@router.post('', response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def create_document(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    document_service = DocumentService(DocumentRepository(db))
    content = bytearray()
    max_size = get_settings().max_upload_size_bytes
    while chunk := await file.read(min(1024 * 1024, max_size + 1 - len(content))):
        content.extend(chunk)
        if len(content) > max_size:
            raise FileTooLargeError(f'File exceeds {get_settings().max_upload_size_mb} MB limit.')
    document = await document_service.create_document(
        user_id=current_user.id,
        filename=file.filename or 'upload',
        file_obj=bytes(content),
        content_type=file.content_type,
    )
    job = IngestionJob(document_id=document.id)
    db.add(job)
    await db.commit()
    await db.refresh(job)
    asyncio.create_task(_run_ingestion(document.id, job.id))
    return DocumentRead.model_validate(document)


async def _run_ingestion(document_id: str, job_id) -> None:
    from app.db.database import AsyncSessionLocal
    from app.services.ingestion_service import IngestionService

    async with AsyncSessionLocal() as session:
        await IngestionService(session).ingest(document_id, job_id)


@router.get('', response_model=list[DocumentRead])
async def list_documents(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    document_service = DocumentService(DocumentRepository(db))
    documents = await document_service.list_documents(current_user.id)
    return [DocumentRead.model_validate(item) for item in documents]


@router.get('/{document_id}', response_model=DocumentRead)
async def get_document(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    document_service = DocumentService(DocumentRepository(db))
    document = await document_service.get_document(document_id, current_user.id)
    return DocumentRead.model_validate(document)


@router.delete('/{document_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    document_service = DocumentService(DocumentRepository(db))
    await document_service.delete_document(document_id, current_user.id)
    return None
