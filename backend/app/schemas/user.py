from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr
    role: str = 'user'


class UserCreate(BaseModel):
    id: str
    email: EmailStr
    role: str = 'user'
