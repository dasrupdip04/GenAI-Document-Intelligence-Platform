from __future__ import annotations

import asyncio
import logging
import re
from functools import cached_property
from typing import Protocol

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

GEMINI_REQUEST_TIMEOUT_SECONDS = 15
GEMINI_REQUEST_TIMEOUT_MS = GEMINI_REQUEST_TIMEOUT_SECONDS * 1000

# Only transient upstream failures are retried.
# 429 is deliberately NOT retried because it is a quota/rate-limit condition.
RETRYABLE_STATUS_CODES = {500, 502, 503, 504}
MAX_ATTEMPTS = 2
RETRY_DELAY_SECONDS = 0.75


class GeminiProviderError(Exception):
    def __init__(
        self,
        *,
        operation: str,
        model: str,
        message: str,
        upstream_http_status: int | None = None,
        gemini_code: str | None = None,
        retry_attempt: int = 1,
    ) -> None:
        self.provider = "gemini"
        self.operation = operation
        self.model = model
        self.upstream_http_status = upstream_http_status
        self.gemini_code = gemini_code
        self.retry_attempt = retry_attempt
        self.safe_message = message
        super().__init__(message)


class GeminiConfigurationError(GeminiProviderError):
    pass


class GeminiMalformedResponseError(GeminiProviderError):
    pass


class GeminiTimeoutError(GeminiProviderError):
    def __init__(
        self,
        *,
        operation: str,
        model: str,
        retry_attempt: int,
    ) -> None:
        super().__init__(
            operation=operation,
            model=model,
            message="Gemini request timed out.",
            gemini_code="TIMEOUT",
            retry_attempt=retry_attempt,
        )


class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]:
        ...


class LLMProvider(Protocol):
    async def generate(self, prompt: str) -> str:
        ...


class GeminiProvider:
    def __init__(self) -> None:
        self.settings = get_settings()

    @cached_property
    def client(self):
        if not self.settings.gemini_api_key:
            raise GeminiConfigurationError(
                operation="client",
                model=self.settings.gemini_model,
                message="GEMINI_API_KEY is not configured.",
            )

        from google import genai
        from google.genai import types

        return genai.Client(
            api_key=self.settings.gemini_api_key,
            http_options=types.HttpOptions(
                timeout=GEMINI_REQUEST_TIMEOUT_MS,
            ),
        )

    def _safe_message(self, error: Exception) -> str:
        message = str(getattr(error, "message", "") or error or "")

        if self.settings.gemini_api_key:
            message = message.replace(
                self.settings.gemini_api_key,
                "[REDACTED]",
            )

        message = re.sub(
            r"(?i)bearer\s+[^\s,;]+",
            "Bearer [REDACTED]",
            message,
        )

        message = re.sub(
            r"AIza[0-9A-Za-z_-]{20,}",
            "[REDACTED]",
            message,
        )

        message = re.sub(
            r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+",
            "[REDACTED]",
            message,
        )

        return message[:400]

    def _log_failure(
        self,
        operation: str,
        model: str,
        error: Exception,
        retry_attempt: int,
    ) -> None:
        logger.error(
            (
                "provider_failure provider=gemini "
                "operation=%s model=%s "
                "upstream_http_status=%s gemini_code=%s "
                "retry_attempt=%s error_type=%s sanitized_message=%s"
            ),
            operation,
            model,
            getattr(error, "code", None),
            getattr(error, "status", None),
            retry_attempt,
            type(error).__name__,
            self._safe_message(error),
        )

    def _provider_error(
        self,
        operation: str,
        model: str,
        error: Exception,
        retry_attempt: int,
    ) -> GeminiProviderError:
        message = (
            self._safe_message(error)
            or "Gemini request failed."
        )

        return GeminiProviderError(
            operation=operation,
            model=model,
            message=message,
            upstream_http_status=getattr(error, "code", None),
            gemini_code=getattr(error, "status", None),
            retry_attempt=retry_attempt,
        )

    @staticmethod
    def _status_code(error: Exception) -> int | None:
        value = getattr(error, "code", None)

        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _is_retryable(error: Exception) -> bool:
        return (
            getattr(error, "code", None)
            in RETRYABLE_STATUS_CODES
        )

    async def embed(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        if not texts:
            return []

        from google.genai import types

        model = self.settings.gemini_embedding_model

        for attempt in range(MAX_ATTEMPTS):
            retry_attempt = attempt + 1

            try:
                async with asyncio.timeout(
                    GEMINI_REQUEST_TIMEOUT_SECONDS
                ):
                    response = await self.client.aio.models.embed_content(
                        model=model,
                        contents=texts,
                        config=types.EmbedContentConfig(
                            output_dimensionality=(
                                self.settings.embedding_dimensions
                            ),
                        ),
                    )

                vectors = [
                    item.values
                    for item in response.embeddings
                ]

                if len(vectors) != len(texts):
                    raise GeminiMalformedResponseError(
                        operation="embedding",
                        model=model,
                        message=(
                            "Gemini embedding provider returned "
                            "an unexpected result count."
                        ),
                        retry_attempt=retry_attempt,
                    )

                if any(
                    len(vector)
                    != self.settings.embedding_dimensions
                    for vector in vectors
                ):
                    raise GeminiMalformedResponseError(
                        operation="embedding",
                        model=model,
                        message=(
                            "Gemini embedding dimension did not "
                            "match configured pgvector dimension."
                        ),
                        retry_attempt=retry_attempt,
                    )

                return vectors

            except GeminiProviderError:
                raise

            except (
                TimeoutError,
                httpx.TimeoutException,
            ) as error:
                timeout_error = GeminiTimeoutError(
                    operation="embedding",
                    model=model,
                    retry_attempt=retry_attempt,
                )

                self._log_failure(
                    "embedding",
                    model,
                    timeout_error,
                    retry_attempt,
                )

                # Do not retry timeouts here. A second 15-second
                # embedding attempt can unnecessarily delay ingestion.
                raise timeout_error from error

            except Exception as error:
                self._log_failure(
                    "embedding",
                    model,
                    error,
                    retry_attempt,
                )

                status = self._status_code(error)

                # Never retry quota/rate-limit responses.
                if (
                    attempt < MAX_ATTEMPTS - 1
                    and status in RETRYABLE_STATUS_CODES
                ):
                    await asyncio.sleep(RETRY_DELAY_SECONDS)
                    continue

                raise self._provider_error(
                    "embedding",
                    model,
                    error,
                    retry_attempt,
                ) from error

        raise RuntimeError("Unreachable embedding retry state.")

    async def generate(
        self,
        prompt: str,
    ) -> str:
        model = self.settings.gemini_model

        for attempt in range(MAX_ATTEMPTS):
            retry_attempt = attempt + 1

            try:
                async with asyncio.timeout(
                    GEMINI_REQUEST_TIMEOUT_SECONDS
                ):
                    response = (
                        await self.client.aio.models.generate_content(
                            model=model,
                            contents=prompt,
                        )
                    )

                text = (response.text or "").strip()

                if not text:
                    raise GeminiMalformedResponseError(
                        operation="generation",
                        model=model,
                        message=(
                            "Gemini returned an empty "
                            "generation response."
                        ),
                        retry_attempt=retry_attempt,
                    )

                return text

            except GeminiProviderError:
                raise

            except (
                TimeoutError,
                httpx.TimeoutException,
            ) as error:
                timeout_error = GeminiTimeoutError(
                    operation="generation",
                    model=model,
                    retry_attempt=retry_attempt,
                )

                self._log_failure(
                    "generation",
                    model,
                    timeout_error,
                    retry_attempt,
                )

                # A timeout is surfaced immediately rather than
                # creating another long request.
                raise timeout_error from error

            except Exception as error:
                self._log_failure(
                    "generation",
                    model,
                    error,
                    retry_attempt,
                )

                status = self._status_code(error)

                # Exactly one retry for transient 5xx.
                # 429 is intentionally excluded.
                if (
                    attempt < MAX_ATTEMPTS - 1
                    and status in RETRYABLE_STATUS_CODES
                ):
                    await asyncio.sleep(RETRY_DELAY_SECONDS)
                    continue

                raise self._provider_error(
                    "generation",
                    model,
                    error,
                    retry_attempt,
                ) from error

        raise RuntimeError("Unreachable generation retry state.")