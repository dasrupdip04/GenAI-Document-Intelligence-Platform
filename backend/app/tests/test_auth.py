from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.exceptions import AuthenticationError
from app.dependencies.auth import get_current_user


def test_missing_auth_header_returns_401(client: TestClient) -> None:
    response = client.get('/api/v1/auth/me')
    assert response.status_code == 401


def test_invalid_auth_token_returns_401(client: TestClient) -> None:
    response = client.get('/api/v1/auth/me', headers={'Authorization': 'Bearer bad-token'})
    assert response.status_code == 401
