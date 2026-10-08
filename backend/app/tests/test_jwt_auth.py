from __future__ import annotations

from fastapi.testclient import TestClient


def test_invalid_auth_header(client: TestClient) -> None:
    response = client.get('/api/v1/auth/me', headers={'Authorization': 'Token invalid'})
    assert response.status_code == 401
