from __future__ import annotations

from typing import Any

import jwt
from jwt import PyJWKClient

from app.core.config import get_settings
from app.core.exceptions import AuthenticationError


def get_supabase_jwks_client() -> PyJWKClient:
    settings = get_settings()
    return PyJWKClient(settings.supabase_jwks_url)


def verify_supabase_jwt(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        signing_key = get_supabase_jwks_client().get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=['ES256'],
            audience='authenticated',
            issuer=f'{settings.supabase_url}/auth/v1',
            options={'require': ['exp', 'sub', 'aud', 'iss']},
        )
        return payload
    except Exception as exc:
        raise AuthenticationError('Invalid or expired authentication token.') from exc


def extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise AuthenticationError('Authorization header is missing.')

    scheme, _, token = authorization.partition(' ')
    if scheme.lower() != 'bearer' or not token:
        raise AuthenticationError('Bearer token is required.')
    return token
