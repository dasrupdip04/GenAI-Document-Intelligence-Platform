from __future__ import annotations

import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.models.stage2 import Citation, Conversation, ConversationDocument, DocumentChunk, Message
from app.models.document import Document
from app.models.user import User
from app.schemas.conversation import (CitationRead, ConversationCreate, ConversationRead,
    ConversationDocumentAttach, ConversationDocumentRead, ConversationSummary, MessageRead, QuestionCreate)
from app.services.rag_service import RAGService
from app.services.providers import MalformedProviderResponseError, ProviderError
from app.services.retrieval_service import RetrievalService

router = APIRouter(prefix='/api/v1/conversations', tags=['conversations'])
logger = logging.getLogger(__name__)


@router.post('', response_model=ConversationSummary, status_code=201)
async def create_conversation(payload: ConversationCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    conversation = Conversation(user_id=user.id, title=payload.title)
    db.add(conversation)
    await db.flush()
    if payload.document_ids:
        result = await db.execute(select(Document.id).where(
            Document.id.in_(set(payload.document_ids)), Document.user_id == user.id
        ))
        owned_ids = set(result.scalars().all())
        if owned_ids != set(payload.document_ids):
            raise NotFoundError('One or more documents were not found.')
        db.add_all(ConversationDocument(conversation_id=conversation.id, document_id=document_id)
                   for document_id in owned_ids)
    await db.commit(); await db.refresh(conversation)
    return conversation


@router.get('', response_model=list[ConversationSummary])
async def list_conversations(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Conversation).where(Conversation.user_id == user.id).order_by(Conversation.updated_at.desc()))
    return list(result.scalars().all())


@router.delete('/{conversation_id}', status_code=204)
async def delete_conversation(conversation_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    conversation = await _owned_conversation(db, conversation_id, user.id)
    await db.delete(conversation)
    await db.commit()
    return None


@router.get('/{conversation_id}', response_model=ConversationRead)
async def get_conversation(conversation_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    conversation = await _owned_conversation(db, conversation_id, user.id)
    result = await db.execute(select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at))
    messages = list(result.scalars().all())
    out = []
    for message in messages:
        citations = await _message_citations(db, message.id)
        out.append(MessageRead(id=message.id, role=message.role, content=message.content, created_at=message.created_at, citations=citations))
    documents_result = await db.execute(select(Document).join(
        ConversationDocument, ConversationDocument.document_id == Document.id
    ).where(ConversationDocument.conversation_id == conversation.id, Document.user_id == user.id))
    documents = [ConversationDocumentRead(id=d.id, filename=d.filename, file_type=d.file_type,
                                           status=d.status, error_message=d.error_message)
                 for d in documents_result.scalars().all()]
    return ConversationRead(id=conversation.id, title=conversation.title, created_at=conversation.created_at,
                            updated_at=conversation.updated_at, messages=out, documents=documents)


@router.post('/{conversation_id}/documents', response_model=ConversationDocumentRead, status_code=201)
async def attach_document(conversation_id: str, payload: ConversationDocumentAttach, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    conversation = await _owned_conversation(db, conversation_id, user.id)
    document = await db.scalar(select(Document).where(Document.id == payload.document_id, Document.user_id == user.id))
    if not document:
        raise NotFoundError('Document not found.')
    link = await db.get(ConversationDocument, (conversation.id, document.id))
    if not link:
        db.add(ConversationDocument(conversation_id=conversation.id, document_id=document.id))
        await db.commit()
    return ConversationDocumentRead(id=document.id, filename=document.filename, file_type=document.file_type,
                                    status=document.status, error_message=document.error_message)


@router.delete('/{conversation_id}/documents/{document_id}', status_code=204)
async def detach_document(conversation_id: str, document_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    conversation = await _owned_conversation(db, conversation_id, user.id)
    link = await db.get(ConversationDocument, (conversation.id, document_id))
    if not link:
        raise NotFoundError('Conversation document not found.')
    await db.delete(link)
    await db.commit()
    return None


@router.post('/{conversation_id}/messages', response_model=MessageRead, status_code=201)
async def ask(conversation_id: str, payload: QuestionCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    conversation = await _owned_conversation(db, conversation_id, user.id)
    user_message = Message(conversation_id=conversation.id, role='user', content=payload.content)
    db.add(user_message)
    conversation.updated_at = datetime.now(timezone.utc)
    await db.commit()
    history_result = await db.execute(select(Message).where(
        Message.conversation_id == conversation.id, Message.id != user_message.id
    ).order_by(Message.created_at.desc()).limit(8))
    history = [{'role': m.role, 'content': m.content} for m in reversed(history_result.scalars().all())]
    try:
        attached_result = await db.execute(select(ConversationDocument.document_id).join(
            Document, Document.id == ConversationDocument.document_id
        ).where(ConversationDocument.conversation_id == conversation.id, Document.user_id == user.id,
                Document.status == 'READY'))
        document_ids = list(attached_result.scalars().all())
        result = await RAGService(RetrievalService(db)).answer(user.id, payload.content, history, document_ids)
    except ProviderError as exc:
        await db.rollback()
        logger.error(
            'rag_provider_failure provider=%s operation=%s model=%s upstream_http_status=%s retry_attempt=%s sanitized_message=%s',
            exc.provider, exc.operation, exc.model, exc.upstream_http_status,
            exc.retry_attempt, exc.safe_message,
        )
        raise _provider_http_error(exc) from exc
    except Exception as exc:
        await db.rollback()
        logger.error('rag_pipeline_failure conversation_id=%s error_type=%s', conversation_id, type(exc).__name__)
        raise HTTPException(status_code=500, detail='Unable to process this question right now.') from exc
    assistant = Message(conversation_id=conversation.id, role='assistant', content=result['answer'])
    db.add(assistant); await db.flush()
    ids = [citation['chunk_id'] for citation in result['citations']]
    chunks_result = await db.execute(select(DocumentChunk, Document).join(Document, Document.id == DocumentChunk.document_id)
        .where(DocumentChunk.id.in_(ids), Document.user_id == user.id))
    chunk_docs = {str(chunk.id): (chunk, document) for chunk, document in chunks_result.all()}
    citation_reads = []
    for citation in result['citations']:
        item = chunk_docs.get(citation['chunk_id'])
        if not item: continue
        chunk, document = item
        row = Citation(message_id=assistant.id, chunk_id=chunk.id, document_id=document.id,
                       page_number=chunk.page_number, relevance_score=citation['relevance_score'])
        db.add(row); await db.flush()
        citation_reads.append(CitationRead(id=row.id, chunk_id=chunk.id, document_id=document.id,
            filename=document.filename, page_number=chunk.page_number, relevance_score=row.relevance_score))
    await db.commit(); await db.refresh(assistant)
    return MessageRead(id=assistant.id, role=assistant.role, content=assistant.content,
                       created_at=assistant.created_at, citations=citation_reads)


async def _owned_conversation(db: AsyncSession, conversation_id: str, user_id: str) -> Conversation:
    result = await db.execute(select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user_id))
    conversation = result.scalar_one_or_none()
    if not conversation: raise NotFoundError('Conversation not found.')
    return conversation


async def _message_citations(db: AsyncSession, message_id) -> list[CitationRead]:
    result = await db.execute(select(Citation, Document).join(Document, Document.id == Citation.document_id)
        .where(Citation.message_id == message_id))
    return [CitationRead(id=c.id, chunk_id=c.chunk_id, document_id=d.id, filename=d.filename,
                         page_number=c.page_number, relevance_score=c.relevance_score) for c, d in result.all()]


def _provider_http_error(error: ProviderError) -> HTTPException:
    status = error.upstream_http_status
    provider = error.provider.capitalize()
    if status == 429:
        return HTTPException(status_code=429, detail=f'{provider} quota/rate limit reached. Please try again later.')
    if status == 503 or (status is not None and status >= 500):
        return HTTPException(status_code=503, detail=f'{provider} is temporarily unavailable. Please try again.')
    if status in {401, 403}:
        return HTTPException(status_code=502, detail=f'{provider} authentication or permission configuration is invalid.')
    if status == 404:
        return HTTPException(status_code=502, detail=f'The configured {provider} model is unavailable.')
    if isinstance(error, MalformedProviderResponseError) or status == 200:
        return HTTPException(status_code=502, detail=f'{provider} returned an invalid response.')
    if status is None:
        return HTTPException(status_code=500, detail=f'{provider} provider configuration failed: {error.safe_message}')
    return HTTPException(status_code=502, detail=f'{provider} rejected the request configuration.')
