from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base application error."""

    status_code = 500
    detail = 'Internal server error'

    def __init__(self, detail: str | None = None, **kwargs: Any) -> None:
        self.detail = detail or self.detail
        self.payload = kwargs
        super().__init__(self.detail)


class AuthenticationError(AppError):
    status_code = 401
    detail = 'Authentication required.'


class ForbiddenError(AppError):
    status_code = 403
    detail = 'Forbidden.'


class NotFoundError(AppError):
    status_code = 404
    detail = 'Not found.'


class ValidationError(AppError):
    status_code = 400
    detail = 'Validation failed.'


class UnsupportedFileTypeError(ValidationError):
    status_code = 415
    detail = 'Unsupported file type.'


class FileTooLargeError(ValidationError):
    status_code = 413
    detail = 'File too large.'


class EmptyFileError(ValidationError):
    status_code = 400
    detail = 'File is empty.'


class InternalServerError(AppError):
    status_code = 500
    detail = 'Internal server error.'
