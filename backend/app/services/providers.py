from __future__ import annotations

from typing import Protocol

from app.core.config import get_settings


class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class LLMProvider(Protocol):
    async def generate(self, prompt: str) -> str: ...


class GeminiProvider:
    def __init__(self) -> None:
        self.settings = get_settings()

    def _client(self):
        if not self.settings.gemini_api_key:
            raise RuntimeError('Gemini is not configured. Set GEMINI_API_KEY.')
        from google import genai
        return genai.Client(api_key=self.settings.gemini_api_key)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        from google.genai import types
        response = await self._client().aio.models.embed_content(
            model=self.settings.gemini_embedding_model,
            contents=texts,
            config=types.EmbedContentConfig(output_dimensionality=self.settings.embedding_dimensions),
        )
        return [item.values for item in response.embeddings]

    async def generate(self, prompt: str) -> str:
        response = await self._client().aio.models.generate_content(model=self.settings.gemini_model, contents=prompt)
        return response.text or ''
