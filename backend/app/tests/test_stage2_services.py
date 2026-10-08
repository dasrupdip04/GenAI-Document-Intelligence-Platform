from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from uuid import uuid4

from app.models.document import Document
from app.models.stage2 import IngestionJob
from app.services.extraction import DocumentExtractor, ExtractedPage, RecursiveChunker
from app.services.ingestion_service import IngestionService
from app.services.rag_service import RAGService
from app.services.retrieval_service import RetrievedChunk, RetrievalService


def test_txt_extraction_uses_utf8_and_tmp_path(tmp_path):
    path = tmp_path / 'sample.txt'
    path.write_text('Résumé: a document.', encoding='utf-8')
    assert DocumentExtractor().extract(str(path), 'txt') == [ExtractedPage('Résumé: a document.')]


def test_pdf_extraction_preserves_page_numbers(monkeypatch, tmp_path):
    class Pdf:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def __iter__(self): return iter([SimpleNamespace(get_text=lambda: 'page one'), SimpleNamespace(get_text=lambda: 'page two')])
    monkeypatch.setitem(sys.modules, 'fitz', SimpleNamespace(open=lambda path: Pdf()))
    assert DocumentExtractor().extract(str(tmp_path / 'x.pdf'), 'pdf') == [ExtractedPage('page one', 1), ExtractedPage('page two', 2)]


def test_docx_extraction_collects_paragraphs_and_table(monkeypatch, tmp_path):
    fake_doc = SimpleNamespace(paragraphs=[SimpleNamespace(text='Heading'), SimpleNamespace(text='')], tables=[])
    module = SimpleNamespace(Document=lambda path: fake_doc)
    monkeypatch.setitem(sys.modules, 'docx', module)
    assert DocumentExtractor().extract(str(tmp_path / 'x.docx'), 'docx') == [ExtractedPage('Heading')]


def test_chunker_preserves_source_text_and_bounds_chunks():
    source = ('First sentence. Second sentence.\n\n' * 30).strip()
    chunks = RecursiveChunker(chunk_size=80, overlap=12).split(source)
    assert len(chunks) > 1
    assert all(len(chunk) <= 80 for chunk in chunks)
    assert all(chunk in source for chunk in chunks)


class FakeSession:
    def __init__(self, document, job):
        self.document, self.job = document, job
        self.added = []
        self.rollbacks = 0

    async def get(self, model, key):
        return self.job if model is IngestionJob else self.document

    async def execute(self, statement):
        return None

    def add(self, value):
        self.added.append(value)

    async def commit(self):
        return None

    async def rollback(self):
        self.rollbacks += 1


class FakeEmbedder:
    async def embed(self, texts):
        return [[0.1, 0.2] for _ in texts]


class FakeExtractor:
    def extract(self, path, file_type):
        return [ExtractedPage('test content', 2)]


def test_ingestion_transitions_to_ready_with_mocked_embedder():
    document = SimpleNamespace(id='doc-1', storage_path='/unused', file_type='txt', filename='a.txt', status='PROCESSING', error_message=None)
    job = SimpleNamespace(status='PENDING', started_at=None, completed_at=None, error_message=None)
    session = FakeSession(document, job)
    asyncio.run(IngestionService(session, FakeEmbedder(), FakeExtractor()).ingest('doc-1', uuid4()))
    assert document.status == job.status == 'READY'
    assert len(session.added) == 1
    assert session.added[0].page_number == 2


def test_ingestion_failure_persists_safe_error():
    class BrokenEmbedder:
        async def embed(self, texts):
            raise RuntimeError('private provider payload')
    document = SimpleNamespace(id='doc-1', storage_path='/unused', file_type='txt', filename='a.txt', status='PROCESSING', error_message=None)
    job = SimpleNamespace(status='PENDING', started_at=None, completed_at=None, error_message=None)
    session = FakeSession(document, job)
    asyncio.run(IngestionService(session, BrokenEmbedder(), FakeExtractor()).ingest('doc-1', uuid4()))
    assert document.status == job.status == 'FAILED'
    assert 'private provider payload' not in job.error_message


def test_rag_runs_query_variants_and_returns_real_retrieval_citations():
    chunk = SimpleNamespace(id=uuid4(), content='Supported fact.', page_number=4)
    document = SimpleNamespace(id='doc-1', filename='source.pdf')
    retrieved = RetrievedChunk(chunk=chunk, document=document, score=0.8)

    class Retrieval:
        queries = []
        async def retrieve(self, user_id, query, top_k, document_ids):
            self.queries.append(query)
            return [retrieved]

    class LLM:
        calls = []
        async def generate(self, prompt):
            self.calls.append(prompt)
            return '{"queries":["variant one", "variant two", "variant three"],"step_back":"broader topic"}' if len(self.calls) == 1 else 'Supported fact.'

    retrieval, llm = Retrieval(), LLM()
    result = asyncio.run(RAGService(retrieval, llm).answer('user-1', 'question', []))
    assert len(retrieval.queries) == 5
    assert result['answer'] == 'Supported fact.'
    assert result['citations'][0]['chunk_id'] == str(chunk.id)
    assert result['citations'][0]['page_number'] == 4


def test_rag_with_no_attached_documents_does_not_call_provider():
    class Retrieval:
        async def retrieve(self, *args, **kwargs): raise AssertionError('should not retrieve without attached documents')
    class LLM:
        async def generate(self, prompt): raise AssertionError('should not call Gemini without attached documents')
    result = asyncio.run(RAGService(Retrieval(), LLM()).answer('user', 'question', [], []))
    assert result == {'answer': 'The information is not available in the documents.', 'citations': []}


def test_gemini_embedding_provider_batches_through_mocked_sdk(monkeypatch):
    import types
    from app.services.providers import GeminiProvider

    class FakeModels:
        async def embed_content(self, **kwargs):
            assert kwargs['model'] == 'test-embed'
            assert kwargs['contents'] == ['one', 'two']
            assert kwargs['config'] == {'output_dimensionality': 1}
            return SimpleNamespace(embeddings=[SimpleNamespace(values=[1.0]), SimpleNamespace(values=[2.0])])

    class FakeClient:
        aio = SimpleNamespace(models=FakeModels())

    provider = GeminiProvider.__new__(GeminiProvider)
    provider.settings = SimpleNamespace(gemini_embedding_model='test-embed', embedding_dimensions=1)
    monkeypatch.setattr(provider, '_client', lambda: FakeClient())
    genai = types.ModuleType('google.genai')
    genai.types = SimpleNamespace(EmbedContentConfig=lambda **kwargs: kwargs)
    google = types.ModuleType('google')
    google.genai = genai
    monkeypatch.setitem(sys.modules, 'google', google)
    monkeypatch.setitem(sys.modules, 'google.genai', genai)
    assert asyncio.run(provider.embed(['one', 'two'])) == [[1.0], [2.0]]


def test_gemini_generation_uses_configured_model(monkeypatch):
    from app.services.providers import GeminiProvider

    class FakeModels:
        async def generate_content(self, **kwargs):
            assert kwargs['model'] == 'configured-generation-model'
            return SimpleNamespace(text='grounded response')
    provider = GeminiProvider.__new__(GeminiProvider)
    provider.settings = SimpleNamespace(gemini_model='configured-generation-model', gemini_api_key='test-key')
    monkeypatch.setattr(provider, '_client', lambda: SimpleNamespace(aio=SimpleNamespace(models=FakeModels())))
    assert asyncio.run(provider.generate('prompt')) == 'grounded response'


def test_gemini_generation_retries_transient_provider_failure(monkeypatch):
    import app.services.providers as providers
    from app.services.providers import GeminiProvider
    calls = 0

    class TemporaryError(Exception):
        code = 503
        status = 'UNAVAILABLE'
        message = 'temporary'

    class FakeModels:
        async def generate_content(self, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise TemporaryError()
            return SimpleNamespace(text='grounded response')
    provider = GeminiProvider.__new__(GeminiProvider)
    provider.settings = SimpleNamespace(gemini_model='configured-model', gemini_api_key='')
    monkeypatch.setattr(provider, '_client', lambda: SimpleNamespace(aio=SimpleNamespace(models=FakeModels())))
    async def no_wait(_seconds): return None
    monkeypatch.setattr(providers.asyncio, 'sleep', no_wait)
    assert asyncio.run(provider.generate('prompt')) == 'grounded response'
    assert calls == 2


def test_gemini_generation_timeout_is_bounded_and_maps_to_503(monkeypatch):
    import app.services.providers as providers
    from app.api.conversations import _gemini_http_error
    from app.services.providers import GeminiProvider, GeminiTimeoutError
    calls = 0

    class SlowModels:
        async def generate_content(self, **kwargs):
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.05)

    provider = GeminiProvider.__new__(GeminiProvider)
    provider.settings = SimpleNamespace(gemini_model='gemini-3.8-flash', gemini_api_key='')
    monkeypatch.setattr(provider, '_client', lambda: SimpleNamespace(aio=SimpleNamespace(models=SlowModels())))
    monkeypatch.setattr(providers, 'GEMINI_REQUEST_TIMEOUT_SECONDS', 0.005)
    try:
        asyncio.run(provider.generate('prompt'))
    except GeminiTimeoutError as exc:
        assert exc.gemini_code == 'TIMEOUT'
        assert exc.retry_attempt == 1
        assert _gemini_http_error(exc).status_code == 503
    else:
        raise AssertionError('generation should time out')
    assert calls == 1


def test_gemini_embedding_timeout_is_bounded(monkeypatch):
    import types
    import app.services.providers as providers
    from app.services.providers import GeminiProvider, GeminiTimeoutError

    class SlowModels:
        async def embed_content(self, **kwargs): await asyncio.sleep(0.05)

    genai = types.ModuleType('google.genai')
    genai.types = SimpleNamespace(EmbedContentConfig=lambda **kwargs: kwargs)
    google = types.ModuleType('google')
    google.genai = genai
    monkeypatch.setitem(sys.modules, 'google', google)
    monkeypatch.setitem(sys.modules, 'google.genai', genai)
    provider = GeminiProvider.__new__(GeminiProvider)
    provider.settings = SimpleNamespace(gemini_embedding_model='test-embed', embedding_dimensions=1, gemini_api_key='')
    monkeypatch.setattr(provider, '_client', lambda: SimpleNamespace(aio=SimpleNamespace(models=SlowModels())))
    monkeypatch.setattr(providers, 'GEMINI_REQUEST_TIMEOUT_SECONDS', 0.005)
    try:
        asyncio.run(provider.embed(['one']))
    except GeminiTimeoutError as exc:
        assert exc.operation == 'embedding'
    else:
        raise AssertionError('embedding should time out')


def test_gemini_provider_logs_status_and_redacts_key(caplog):
    from app.services.providers import GeminiProvider
    provider = GeminiProvider.__new__(GeminiProvider)
    provider.settings = SimpleNamespace(gemini_api_key='private-api-key')
    error = SimpleNamespace(message='model unavailable; credential private-api-key', code=404, status='NOT_FOUND')
    with caplog.at_level('ERROR'):
        provider._log_failure('generation', 'gemini-test-model', error, retry_attempt=1)
    assert '404' in caplog.text and 'NOT_FOUND' in caplog.text
    assert 'gemini-test-model' in caplog.text
    assert 'private-api-key' not in caplog.text


def test_retrieval_sql_is_user_scoped_and_supports_cosine_distance():
    class Embedder:
        async def embed(self, texts): return [[0.1] * 768]
    class Result:
        def all(self): return []
    class Session:
        bind = SimpleNamespace(dialect=SimpleNamespace(name='postgresql'))
        async def execute(self, statement):
            from sqlalchemy.dialects import postgresql
            sql = str(statement.compile(dialect=postgresql.dialect()))
            assert 'documents.user_id = ' in sql
            assert '<=>' in sql
            return Result()
    assert asyncio.run(RetrievalService(Session(), Embedder()).retrieve('owner-1', 'question')) == []


def test_conversation_owner_lookup_returns_not_found_for_other_user():
    from app.api.conversations import _owned_conversation
    from app.core.exceptions import NotFoundError

    class Result:
        def scalar_one_or_none(self): return None
    class Session:
        async def execute(self, statement):
            assert 'conversations.user_id' in str(statement)
            return Result()
    try:
        asyncio.run(_owned_conversation(Session(), str(uuid4()), 'other-user'))
    except NotFoundError:
        return
    raise AssertionError('non-owned conversation must be hidden as not found')


def test_pgvector_column_dimensions_match_runtime_configuration():
    from app.core.config import get_settings
    from app.models.stage2 import DocumentChunk
    assert DocumentChunk.__table__.c.embedding.type.dimensions == get_settings().embedding_dimensions == 768
