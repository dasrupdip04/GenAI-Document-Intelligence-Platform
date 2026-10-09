from __future__ import annotations

import asyncio
import logging
import os
from functools import cached_property
from pathlib import Path
from typing import Protocol
from urllib.request import urlretrieve

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
GROQ_TIMEOUT_SECONDS = 15
RETRYABLE_STATUS_CODES = {500, 502, 503, 504}


class ProviderError(Exception):
    def __init__(self, *, provider: str, model: str, message: str,
                 status: int | None = None, attempt: int = 1,
                 operation: str = 'generation', upstream_http_status: int | None = None,
                 gemini_code: str | None = None, retry_attempt: int | None = None):
        self.provider = provider
        self.model = model
        self.operation = operation
        self.upstream_http_status = status if status is not None else upstream_http_status
        self.provider_code = gemini_code
        self.retry_attempt = retry_attempt if retry_attempt is not None else attempt
        self.safe_message = message
        super().__init__(message)


class GeminiProviderError(ProviderError):
    def __init__(self, *, operation: str, model: str, message: str,
                 upstream_http_status: int | None = None, gemini_code: str | None = None,
                 retry_attempt: int = 1):
        super().__init__(provider='gemini', model=model, message=message,
                         operation=operation, upstream_http_status=upstream_http_status,
                         gemini_code=gemini_code, retry_attempt=retry_attempt)


class GeminiConfigurationError(GeminiProviderError):
    pass


class GeminiMalformedResponseError(GeminiProviderError):
    pass


class GeminiTimeoutError(GeminiProviderError):
    def __init__(self, *, operation: str, model: str, retry_attempt: int):
        super().__init__(operation=operation, model=model, message='Gemini request timed out.',
                         gemini_code='TIMEOUT', retry_attempt=retry_attempt)


class MalformedProviderResponseError(ProviderError):
    pass


class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class LLMProvider(Protocol):
    async def generate(self, prompt: str) -> str: ...


class LocalEmbeddingProvider:
    MODEL_REPO = 'sentence-transformers/all-MiniLM-L6-v2'
    MODEL_REVISION = '10dbd2f06a8baf40ad285b037edda610c1b9a57c'
    DIMENSIONS = 384

    @cached_property
    def runtime(self):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        settings = get_settings()
        cache = Path(settings.hf_home or os.getenv('HF_HOME', str(Path.home() / '.cache' / 'huggingface'))) / 'minilm-onnx'
        cache.mkdir(parents=True, exist_ok=True)
        base = f'https://huggingface.co/{self.MODEL_REPO}/resolve/{self.MODEL_REVISION}'
        model_path, tokenizer_path = cache / 'model.onnx', cache / 'tokenizer.json'
        for path, url in ((model_path, f'{base}/onnx/model.onnx'),
                          (tokenizer_path, f'{base}/tokenizer.json')):
            if not path.exists():
                temp = path.with_suffix(path.suffix + '.download')
                try:
                    urlretrieve(url, temp)
                    temp.replace(path)
                except Exception as exc:
                    temp.unlink(missing_ok=True)
                    raise RuntimeError(f'Could not download MiniLM ONNX assets to {cache}: {exc}') from exc
        tokenizer = Tokenizer.from_file(str(tokenizer_path))
        tokenizer.enable_truncation(max_length=256)
        session = ort.InferenceSession(str(model_path), providers=['CPUExecutionProvider'])
        return tokenizer, session

    def _encode(self, texts: list[str]) -> list[list[float]]:
        import numpy as np

        tokenizer, session = self.runtime
        tokens = tokenizer.encode_batch(texts)
        width = max(len(item.ids) for item in tokens)
        ids = np.zeros((len(tokens), width), dtype=np.int64)
        mask = np.zeros_like(ids)
        types = np.zeros_like(ids)
        for row, item in enumerate(tokens):
            size = len(item.ids)
            ids[row, :size], mask[row, :size], types[row, :size] = item.ids, item.attention_mask, item.type_ids
        feeds = {'input_ids': ids, 'attention_mask': mask}
        if any(item.name == 'token_type_ids' for item in session.get_inputs()):
            feeds['token_type_ids'] = types
        hidden = session.run(None, feeds)[0]
        weights = mask[:, :, None].astype(hidden.dtype)
        pooled = (hidden * weights).sum(axis=1) / np.maximum(weights.sum(axis=1), 1)
        pooled /= np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12)
        if pooled.shape != (len(texts), self.DIMENSIONS):
            raise ValueError('MiniLM ONNX model returned an unexpected vector shape (expected 384).')
        return pooled.astype(np.float32).tolist()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return await asyncio.to_thread(self._encode, texts)


class GroqProvider:
    def __init__(self) -> None:
        settings = get_settings()
        self.api_key = settings.groq_api_key
        self.model = settings.groq_model

    async def generate(self, prompt: str) -> str:
        if not self.api_key:
            raise ProviderError(provider='groq', model=self.model,
                                message='GROQ_API_KEY is not configured.')
        for attempt in range(1, 3):
            try:
                async with httpx.AsyncClient(timeout=GROQ_TIMEOUT_SECONDS) as client:
                    response = await client.post(
                        'https://api.groq.com/openai/v1/chat/completions',
                        headers={'Authorization': f'Bearer {self.api_key}'},
                        json={'model': self.model, 'messages': [{'role': 'user', 'content': prompt}]},
                    )
            except httpx.TimeoutException as exc:
                raise ProviderError(provider='groq', model=self.model,
                                    message='Groq request timed out.', status=504,
                                    attempt=attempt) from exc
            except httpx.RequestError as exc:
                raise ProviderError(provider='groq', model=self.model,
                                    message='Could not connect to Groq.', attempt=attempt) from exc
            if response.status_code in RETRYABLE_STATUS_CODES and attempt == 1:
                await asyncio.sleep(0.5)
                continue
            if response.status_code >= 400:
                try:
                    message = response.json().get('error', {}).get('message', 'Groq request failed.')
                except (ValueError, AttributeError):
                    message = 'Groq request failed.'
                message = str(message).replace(self.api_key, '[REDACTED]')[:300]
                logger.error('provider_failure provider=groq model=%s status=%s retry_attempt=%s message=%s',
                             self.model, response.status_code, attempt, message)
                raise ProviderError(provider='groq', model=self.model, message=message,
                                    status=response.status_code, attempt=attempt)
            try:
                answer = response.json()['choices'][0]['message']['content']
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                raise ProviderError(provider='groq', model=self.model,
                                    message='Groq returned a malformed response.',
                                    status=response.status_code, attempt=attempt) from exc
            if not isinstance(answer, str) or not answer.strip():
                raise ProviderError(provider='groq', model=self.model,
                                    message='Groq returned an empty response.',
                                    status=response.status_code, attempt=attempt)
            return answer.strip()
        raise ProviderError(provider='groq', model=self.model,
                            message='Groq request failed after retry.', attempt=2)
