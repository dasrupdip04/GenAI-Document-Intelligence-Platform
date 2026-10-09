from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
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
    groq_api_key: str = ''
    groq_model: str = 'openai/gpt-oss-120b'
    embedding_model: str = 'sentence-transformers/all-MiniLM-L6-v2'
    hf_home: str = './model-cache'
    embedding_dimensions: int = Field(
        default=384,
        validation_alias=AliasChoices('EMBEDDING_DIMENSION', 'EMBEDDING_DIMENSIONS', 'embedding_dimensions'),
    )

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
