from __future__ import annotations

from app.models.user import User
from app.repositories.user_repository import UserRepository


class UserService:
    def __init__(self, user_repository: UserRepository) -> None:
        self.user_repository = user_repository

    async def get_or_create_user(self, user_id: str, email: str, role: str = 'user') -> User:
        return await self.user_repository.upsert(user_id=user_id, email=email, role=role)
