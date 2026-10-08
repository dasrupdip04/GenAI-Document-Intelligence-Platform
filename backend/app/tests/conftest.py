from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base, get_db
from app.main import app

TEST_DATABASE_URL = 'sqlite+aiosqlite:///:memory:'

_test_engine = None
_test_async_session_maker = None


@pytest.fixture(scope='session', autouse=True)
def setup_test_db() -> None:
    global _test_engine, _test_async_session_maker
    
    async def _setup():
        global _test_engine, _test_async_session_maker
        _test_engine = create_async_engine(TEST_DATABASE_URL, future=True)
        async with _test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        _test_async_session_maker = sessionmaker(_test_engine, class_=AsyncSession, expire_on_commit=False)
    
    asyncio.run(_setup())
    yield
    
    async def _teardown():
        global _test_engine
        if _test_engine:
            await _test_engine.dispose()
    
    asyncio.run(_teardown())


@pytest.fixture
def db_session() -> AsyncGenerator[AsyncSession, None]:
    async def _get_session():
        async with _test_async_session_maker() as session:
            yield session
    
    # For sync test fixtures using TestClient, we need to handle async manually
    loop = asyncio.new_event_loop()
    gen = _get_session()
    session = loop.run_until_complete(gen.__anext__())
    yield session
    try:
        loop.run_until_complete(gen.__anext__())
    except StopAsyncIteration:
        pass
    finally:
        loop.close()


@pytest.fixture
def client(db_session: AsyncSession) -> TestClient:
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as api_client:
        yield api_client
    app.dependency_overrides.clear()

