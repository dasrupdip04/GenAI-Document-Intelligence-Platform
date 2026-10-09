from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest

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


@pytest.mark.parametrize("overlap", [80, 81])
def test_chunker_rejects_overlap_at_least_chunk_size(overlap):
    with pytest.raises(ValueError, match="smaller than chunk size"):
        RecursiveChunker(chunk_size=80, overlap=overlap)


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
        async def retrieve_many(self, user_id, queries, top_k, document_ids):
            self.queries.extend(queries)
            return [[retrieved] for _ in queries]

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


def test_local_embedding_provider_batches_384d_vectors(monkeypatch):
    import numpy as np
    from app.services.providers import LocalEmbeddingProvider

    class Token:
        ids=[1, 2]; attention_mask=[1, 1]; type_ids=[0, 0]
    class Tokenizer:
        def encode_batch(self, texts):
            assert texts == ['one', 'two']
            return [Token(), Token()]
    class Session:
        calls=0
        def get_inputs(self): return [SimpleNamespace(name='input_ids'), SimpleNamespace(name='attention_mask')]
        def run(self, _outputs, feeds):
            self.calls += 1
            assert feeds['input_ids'].shape == (2, 2)
            return [np.ones((2, 2, 384), dtype=np.float32)]

    provider=LocalEmbeddingProvider(); session=Session()
    provider.runtime=(Tokenizer(), session)
    vectors=asyncio.run(provider.embed(['one', 'two']))
    assert session.calls == 1 and len(vectors) == 2
    assert all(len(vector) == 384 for vector in vectors)


def test_ingestion_retrieval_use_local_embedding_provider_by_default():
    from app.services.providers import LocalEmbeddingProvider
    assert isinstance(IngestionService(object()).embedder, LocalEmbeddingProvider)
    assert isinstance(RetrievalService(object()).embedder, LocalEmbeddingProvider)


def test_retrieval_sql_is_user_scoped_and_supports_cosine_distance():
    class Embedder:
        async def embed(self, texts): return [[0.1] * 384]
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


def test_retrieve_many_batches_all_embeddings_in_one_call():
    class Embedder:
        calls = []

        async def embed(self, texts):
            self.calls.append(texts)
            return [[0.1] * 384 for _ in texts]

    class Result:
        def all(self):
            return []

    class Session:
        bind = SimpleNamespace(dialect=SimpleNamespace(name='postgresql'))
        calls = 0

        async def execute(self, _statement):
            self.calls += 1
            return Result()

    embedder = Embedder()
    session = Session()
    results = asyncio.run(RetrievalService(session, embedder).retrieve_many(
        'owner-1', ['original', 'variant one', 'step back']))

    assert embedder.calls == [['original', 'variant one', 'step back']]
    assert session.calls == 3
    assert results == [[], [], []]


def test_retrieve_many_deduplicates_queries_before_embedding():
    class Embedder:
        calls = []

        async def embed(self, texts):
            self.calls.append(texts)
            return [[0.1] * 384 for _ in texts]

    class Result:
        def all(self):
            return []

    class Session:
        bind = SimpleNamespace(dialect=SimpleNamespace(name='postgresql'))
        calls = 0

        async def execute(self, _statement):
            self.calls += 1
            return Result()

    embedder = Embedder()
    session = Session()
    results = asyncio.run(RetrievalService(session, embedder).retrieve_many(
        'owner-1', [' question ', 'question', 'variant']))

    assert embedder.calls == [['question', 'variant']]
    assert session.calls == 2
    assert results == [[], []]


def test_retrieve_remains_compatible_with_single_query():
    class Embedder:
        calls = []

        async def embed(self, texts):
            self.calls.append(texts)
            return [[0.1] * 384]

    class Result:
        def all(self):
            return []

    class Session:
        bind = SimpleNamespace(dialect=SimpleNamespace(name='postgresql'))

        async def execute(self, _statement):
            return Result()

    embedder = Embedder()
    result = asyncio.run(RetrievalService(Session(), embedder).retrieve(
        'owner-1', 'question'))

    assert embedder.calls == [['question']]
    assert result == []


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
    assert DocumentChunk.__table__.c.embedding.type.dimensions == get_settings().embedding_dimensions == 384
