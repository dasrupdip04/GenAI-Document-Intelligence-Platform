from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends, HTTPException

from app.db.database import get_db

router = APIRouter(tags=['health'])


@router.get('/health')
async def health() -> dict[str, str]:
    return {'status': 'ok'}


@router.get('/health/db')
async def database_health(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    try:
        await db.execute(text('SELECT 1'))
    except Exception as exc:
        raise HTTPException(status_code=503, detail='Database unavailable.') from exc
    return {'status': 'ok', 'database': 'ok'}
