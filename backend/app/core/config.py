from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized application settings."""

    model_config = SettingsConfigDict(
        env_file=['.env', '../.env'],
        env_file_encoding='utf-8',
        case_sensitive=False,
        extra='ignore',
    )

    app_name: str = 'document-intelligence-platform'
    environment: str = 'development'
    log_level: str = 'INFO'

    database_url: str
    supabase_url: str
    supabase_jwks_url: str
    storage_path: str = './storage/documents'
    max_upload_size_mb: int = 10
    gemini_api_key: str = ''
    gemini_model: str = 'gemini-2.0-flash'
    gemini_embedding_model: str = 'gemini-embedding-001'
    embedding_dimensions: int = 768

    @field_validator('storage_path')
    @classmethod
    def validate_storage_path(cls, value: str) -> str:
        return str(Path(value))

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
