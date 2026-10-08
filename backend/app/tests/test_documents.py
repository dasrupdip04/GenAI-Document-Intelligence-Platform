from __future__ import annotations

import io

from fastapi.testclient import TestClient

from app.dependencies.auth import get_current_user
from app.main import app


def _override_auth(user_id: str = 'user-123', email: str = 'user@example.com') -> None:
    async def fake_get_current_user():
        from app.models.user import User

        return User(id=user_id, email=email, role='user')

    app.dependency_overrides[get_current_user] = fake_get_current_user


def test_document_creation(client: TestClient) -> None:
    _override_auth()
    response = client.post(
        '/api/v1/documents',
        files={'file': ('sample.txt', io.BytesIO(b'hello world'), 'text/plain')},
        headers={'Authorization': 'Bearer test-token'},
    )
    assert response.status_code == 201
    assert response.json()['filename'] == 'sample.txt'


def test_document_listing(client: TestClient) -> None:
    _override_auth()
    client.post(
        '/api/v1/documents',
        files={'file': ('sample.txt', io.BytesIO(b'hello world'), 'text/plain')},
        headers={'Authorization': 'Bearer test-token'},
    )
    response = client.get('/api/v1/documents', headers={'Authorization': 'Bearer test-token'})
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_document_retrieval(client: TestClient) -> None:
    _override_auth()
    created = client.post(
        '/api/v1/documents',
        files={'file': ('sample.txt', io.BytesIO(b'hello world'), 'text/plain')},
        headers={'Authorization': 'Bearer test-token'},
    )
    doc_id = created.json()['id']
    response = client.get(f'/api/v1/documents/{doc_id}', headers={'Authorization': 'Bearer test-token'})
    assert response.status_code == 200
    assert response.json()['id'] == doc_id


def test_document_deletion(client: TestClient) -> None:
    _override_auth()
    created = client.post(
        '/api/v1/documents',
        files={'file': ('sample.txt', io.BytesIO(b'hello world'), 'text/plain')},
        headers={'Authorization': 'Bearer test-token'},
    )
    doc_id = created.json()['id']
    response = client.delete(f'/api/v1/documents/{doc_id}', headers={'Authorization': 'Bearer test-token'})
    assert response.status_code == 204


def test_ownership_enforcement(client: TestClient) -> None:
    _override_auth(user_id='user-1')
    created = client.post(
        '/api/v1/documents',
        files={'file': ('sample.txt', io.BytesIO(b'hello world'), 'text/plain')},
        headers={'Authorization': 'Bearer test-token'},
    )
    doc_id = created.json()['id']
    _override_auth(user_id='user-2')
    response = client.get(f'/api/v1/documents/{doc_id}', headers={'Authorization': 'Bearer test-token'})
    assert response.status_code == 404


def test_unsupported_file_extension(client: TestClient) -> None:
    _override_auth()
    response = client.post(
        '/api/v1/documents',
        files={'file': ('sample.md', io.BytesIO(b'hello world'), 'text/markdown')},
        headers={'Authorization': 'Bearer test-token'},
    )
    assert response.status_code == 415


def test_oversized_file(client: TestClient) -> None:
    _override_auth()
    response = client.post(
        '/api/v1/documents',
        files={'file': ('sample.txt', io.BytesIO(b'a' * 20000000), 'text/plain')},
        headers={'Authorization': 'Bearer test-token'},
    )
    assert response.status_code in (413, 400)


def test_empty_file(client: TestClient) -> None:
    _override_auth()
    response = client.post(
        '/api/v1/documents',
        files={'file': ('empty.txt', io.BytesIO(b''), 'text/plain')},
        headers={'Authorization': 'Bearer test-token'},
    )
    assert response.status_code == 400
