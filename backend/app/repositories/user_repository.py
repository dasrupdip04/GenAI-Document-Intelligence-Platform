from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, user_id: str) -> User | None:
        result = await self.session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def create(self, user: User) -> User:
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def upsert(self, user_id: str, email: str, role: str = 'user') -> User:
        existing = await self.get_by_id(user_id)
        if existing:
            existing.email = email
            existing.role = role
            await self.session.commit()
            await self.session.refresh(existing)
            return existing

        new_user = User(id=user_id, email=email, role=role)
        return await self.create(new_user)
