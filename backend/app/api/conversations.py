from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.models.stage2 import Citation, Conversation, DocumentChunk, Message
from app.models.document import Document
from app.models.user import User
from app.schemas.conversation import (CitationRead, ConversationCreate, ConversationRead,
    ConversationSummary, MessageRead, QuestionCreate)
from app.services.rag_service import RAGService
from app.services.retrieval_service import RetrievalService

router = APIRouter(prefix='/api/v1/conversations', tags=['conversations'])


@router.post('', response_model=ConversationSummary, status_code=201)
async def create_conversation(payload: ConversationCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    conversation = Conversation(user_id=user.id, title=payload.title)
    db.add(conversation); await db.commit(); await db.refresh(conversation)
    return conversation


@router.get('', response_model=list[ConversationSummary])
async def list_conversations(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Conversation).where(Conversation.user_id == user.id).order_by(Conversation.updated_at.desc()))
    return list(result.scalars().all())


@router.get('/{conversation_id}', response_model=ConversationRead)
async def get_conversation(conversation_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    conversation = await _owned_conversation(db, conversation_id, user.id)
    result = await db.execute(select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at))
    messages = list(result.scalars().all())
    out = []
    for message in messages:
        citations = await _message_citations(db, message.id)
        out.append(MessageRead(id=message.id, role=message.role, content=message.content, created_at=message.created_at, citations=citations))
    return ConversationRead(id=conversation.id, title=conversation.title, created_at=conversation.created_at,
                            updated_at=conversation.updated_at, messages=out)


@router.post('/{conversation_id}/messages', response_model=MessageRead, status_code=201)
async def ask(conversation_id: str, payload: QuestionCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    conversation = await _owned_conversation(db, conversation_id, user.id)
    history_result = await db.execute(select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at.desc()).limit(8))
    history = [{'role': m.role, 'content': m.content} for m in reversed(history_result.scalars().all())]
    try:
        result = await RAGService(RetrievalService(db)).answer(user.id, payload.content, history, payload.document_ids)
    except Exception as exc:
        await db.rollback()
        import logging
        logging.getLogger(__name__).exception('RAG request failed conversation_id=%s', conversation_id)
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail='Unable to answer right now. Check Gemini configuration and try again.') from exc
    db.add(Message(conversation_id=conversation.id, role='user', content=payload.content))
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
