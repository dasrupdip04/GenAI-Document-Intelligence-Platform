from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import AuthenticationError
from app.core.security import extract_bearer_token, verify_supabase_jwt
from app.db.database import get_db
from app.repositories.user_repository import UserRepository
from app.services.user_service import UserService


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    authorization = request.headers.get('authorization')
    try:
        token = extract_bearer_token(authorization)
        payload = verify_supabase_jwt(token)
    except AuthenticationError as e:
        raise HTTPException(status_code=401, detail=e.detail)

    user_id = payload.get('sub')
    email = payload.get('email')
    if not user_id or not email:
        raise HTTPException(status_code=401, detail='Token is missing required identity claims.')

    user_service = UserService(UserRepository(db))
    user = await user_service.get_or_create_user(user_id=user_id, email=email)
    return user


async def require_auth(
    current_user=Depends(get_current_user),
):
    return current_user
