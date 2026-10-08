from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

from app.core.config import get_settings
from app.core.exceptions import EmptyFileError, FileTooLargeError, NotFoundError, UnsupportedFileTypeError
from app.models.document import Document
from app.repositories.document_repository import DocumentRepository

ALLOWED_EXTENSIONS = {'.pdf': 'application/pdf', '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', '.txt': 'text/plain'}


class DocumentService:
    def __init__(self, document_repository: DocumentRepository) -> None:
        self.document_repository = document_repository
        self.settings = get_settings()
        self.storage_root = Path(self.settings.storage_path)
        self.storage_root.mkdir(parents=True, exist_ok=True)

    def _validate_file(self, filename: str, content_type: str | None, file_size: int, file_bytes: bytes) -> None:
        if file_size <= 0 or not file_bytes:
            raise EmptyFileError('Uploaded file is empty.')

        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            raise UnsupportedFileTypeError(f'Unsupported file type: {filename}')

        expected_mime = ALLOWED_EXTENSIONS[suffix]
        if content_type and content_type.lower() != expected_mime:
            raise UnsupportedFileTypeError(f'Unexpected MIME type for {filename}')

        if file_size > self.settings.max_upload_size_bytes:
            raise FileTooLargeError(f'File exceeds {self.settings.max_upload_size_mb} MB limit.')

    def _compute_checksum(self, payload: bytes) -> str:
        return hashlib.sha256(payload).hexdigest()

    async def create_document(self, user_id: str, filename: str, file_obj: bytes, content_type: str | None) -> Document:
        filename = filename.replace('\\', '/').rsplit('/', 1)[-1] or 'upload'
        self._validate_file(filename, content_type, len(file_obj), file_obj)

        document_id = str(uuid4())
        checksum = self._compute_checksum(file_obj)
        storage_dir = self.storage_root / user_id
        storage_dir.mkdir(parents=True, exist_ok=True)
        storage_path = storage_dir / f'{document_id}_{filename}'
        storage_path.write_bytes(file_obj)

        document = Document(
            id=document_id,
            user_id=user_id,
            filename=filename,
            file_type=Path(filename).suffix.lower().lstrip('.'),
            file_size=len(file_obj),
            storage_path=str(storage_path),
            status='PROCESSING',
            checksum=checksum,
        )
        return await self.document_repository.create(document)

    async def list_documents(self, user_id: str) -> list[Document]:
        return await self.document_repository.list_for_user(user_id)

    async def get_document(self, document_id: str, user_id: str) -> Document:
        document = await self.document_repository.get_for_user(document_id, user_id)
        if not document:
            raise NotFoundError('Document not found.')
        return document

    async def delete_document(self, document_id: str, user_id: str) -> None:
        document = await self.document_repository.get_for_user(document_id, user_id)
        if not document:
            raise NotFoundError('Document not found.')

        storage_path = Path(document.storage_path)
        if storage_path.exists():
            storage_path.unlink(missing_ok=True)

        await self.document_repository.delete(document)
