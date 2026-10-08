from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api import conversations as conversation_api
from app.models.stage2 import Citation, Conversation, Message
from app.models.user import User
from app.schemas.conversation import QuestionCreate
from app.services.providers import GeminiMalformedResponseError, GeminiProvider, GeminiProviderError
from app.services.rag_service import RAGService


class Result:
    def __init__(self, *, scalar=None, values=(), rows=()):
        self.scalar = scalar
        self.values = list(values)
        self.rows = list(rows)

    def scalar_one_or_none(self): return self.scalar
    def scalars(self): return SimpleNamespace(all=lambda: self.values)
    def all(self): return self.rows


class FakeSession:
    def __init__(self, conversation, chunk, document):
        self.results = [Result(scalar=conversation), Result(values=[]), Result(values=['doc-1']), Result(rows=[(chunk, document)])]
        self.added = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, statement): return self.results.pop(0)
    def add(self, value): self.added.append(value)
    async def commit(self):
        self.commits += 1
        self._assign_ids()
    async def flush(self): self._assign_ids()
    async def refresh(self, value): return None
    async def rollback(self): self.rollbacks += 1
    def _assign_ids(self):
        for item in self.added:
            if hasattr(item, 'id') and getattr(item, 'id') is None:
                item.id = uuid4()


def setup(monkeypatch, rag_result=None, rag_error=None):
    conversation = SimpleNamespace(id=uuid4(), user_id='user-1', updated_at=None)
    chunk = SimpleNamespace(id=uuid4(), page_number=3)
    document = SimpleNamespace(id='doc-1', filename='paper.pdf')
    session = FakeSession(conversation, chunk, document)

    class FakeRAG:
        def __init__(self, retrieval): pass
        async def answer(self, user_id, query, history, document_ids):
            assert user_id == 'user-1'
            assert document_ids == ['doc-1']
            if rag_error:
                raise rag_error
            return rag_result(chunk) if callable(rag_result) else rag_result

    monkeypatch.setattr(conversation_api, 'RAGService', FakeRAG)
    monkeypatch.setattr(conversation_api, 'RetrievalService', lambda db: object())
    user = User(id='user-1', email='user@example.invalid', role='user')
    return conversation, chunk, document, session, user


def test_successful_message_persists_assistant_and_citation(monkeypatch):
    conversation, chunk, document, db, user = setup(monkeypatch, lambda chunk: {
        'answer': 'The method uses two passes.',
        'citations': [{'chunk_id': str(chunk.id), 'relevance_score': 0.91}],
    })
    response = asyncio.run(conversation_api.ask(str(conversation.id), QuestionCreate(content='Describe it'), user, db))
    assert response.content == 'The method uses two passes.'
    assert len(response.citations) == 1
    assert response.citations[0].chunk_id == chunk.id
    assert response.citations[0].page_number == 3
    assert [item.role for item in db.added if isinstance(item, Message)] == ['user', 'assistant']
    assert sum(isinstance(item, Citation) for item in db.added) == 1


@pytest.mark.parametrize(('upstream_status', 'expected_status', 'expected_detail'), [
    (429, 429, 'Gemini quota/rate limit reached.'),
    (503, 503, 'Gemini is temporarily unavailable.'),
])
def test_gemini_http_errors_are_mapped_without_fake_assistant(monkeypatch, upstream_status, expected_status, expected_detail):
    failure = GeminiProviderError(operation='generation', model='gemini-3.8-flash',
                                  message='upstream failure', upstream_http_status=upstream_status,
                                  gemini_code='RESOURCE_EXHAUSTED' if upstream_status == 429 else 'UNAVAILABLE',
                                  retry_attempt=1)
    conversation, chunk, document, db, user = setup(monkeypatch, rag_error=failure)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(conversation_api.ask(str(conversation.id), QuestionCreate(content='Question'), user, db))
    assert exc.value.status_code == expected_status
    assert expected_detail in exc.value.detail
    assert [item.role for item in db.added if isinstance(item, Message)] == ['user']
    assert not any(isinstance(item, Citation) for item in db.added)


def test_malformed_query_expansion_is_not_silently_ignored():
    class LLM:
        async def generate(self, prompt): return 'not-json'
    with pytest.raises(GeminiMalformedResponseError):
        asyncio.run(RAGService(object(), LLM()).answer('user-1', 'question', [], ['doc-1']))


def test_delete_conversation_deletes_only_owned_conversation():
    conversation = SimpleNamespace(id=uuid4(), user_id='user-1')

    class DeleteSession:
        deleted = None
        commits = 0
        async def execute(self, statement): return Result(scalar=conversation)
        async def delete(self, item): self.deleted = item
        async def commit(self): self.commits += 1

    db = DeleteSession()
    result = asyncio.run(conversation_api.delete_conversation(str(conversation.id), User(id='user-1', email='user@example.invalid', role='user'), db))
    assert result is None
    assert db.deleted is conversation
    assert db.commits == 1


def test_delete_conversation_returns_not_found_for_unowned_id():
    from app.core.exceptions import NotFoundError

    class DeleteSession:
        async def execute(self, statement): return Result(scalar=None)
        async def delete(self, item): raise AssertionError('must not delete an unowned conversation')

    with pytest.raises(NotFoundError):
        asyncio.run(conversation_api.delete_conversation(str(uuid4()), User(id='user-1', email='user@example.invalid', role='user'), DeleteSession()))


@pytest.mark.parametrize(('status_code', 'retry_expected'), [(429, 1), (503, 2)])
def test_provider_retry_policy_does_not_retry_429(monkeypatch, status_code, retry_expected):
    import app.services.providers as provider_module
    calls = 0

    class UpstreamError(Exception):
        code = status_code
        status = 'RESOURCE_EXHAUSTED' if status_code == 429 else 'UNAVAILABLE'
        message = 'temporary provider failure'

    class Models:
        async def generate_content(self, **kwargs):
            nonlocal calls
            calls += 1
            raise UpstreamError()

    provider = GeminiProvider.__new__(GeminiProvider)
    provider.settings = SimpleNamespace(gemini_model='gemini-3.8-flash', gemini_api_key='')
    monkeypatch.setattr(provider, '_client', lambda: SimpleNamespace(aio=SimpleNamespace(models=Models())))
    async def no_wait(_seconds): return None
    monkeypatch.setattr(provider_module.asyncio, 'sleep', no_wait)
    with pytest.raises(GeminiProviderError) as exc:
        asyncio.run(provider.generate('generic test prompt'))
    assert calls == retry_expected
    assert exc.value.upstream_http_status == status_code
    assert exc.value.retry_attempt == retry_expected


def test_gemini_empty_response_is_reported_as_malformed(monkeypatch):
    class Models:
        async def generate_content(self, **kwargs): return SimpleNamespace(text=None)
    provider = GeminiProvider.__new__(GeminiProvider)
    provider.settings = SimpleNamespace(gemini_model='gemini-3.8-flash', gemini_api_key='')
    monkeypatch.setattr(provider, '_client', lambda: SimpleNamespace(aio=SimpleNamespace(models=Models())))
    with pytest.raises(GeminiMalformedResponseError):
        asyncio.run(provider.generate('prompt'))
