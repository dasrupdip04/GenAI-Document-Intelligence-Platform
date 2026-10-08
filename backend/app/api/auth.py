from __future__ import annotations

from fastapi import APIRouter, Depends

from app.dependencies.auth import get_current_user
from app.schemas.user import UserRead

router = APIRouter(prefix='/api/v1/auth', tags=['auth'])


@router.get('/me', response_model=UserRead)
async def get_me(current_user=Depends(get_current_user)) -> UserRead:
    return UserRead.model_validate(current_user)
