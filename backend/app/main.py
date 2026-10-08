from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from time import time

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.auth import router as auth_router
from app.api.conversations import router as conversations_router
from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.logging import configure_logging, get_logger

settings = get_settings()
configure_logging()
logger = get_logger(__name__)

app = FastAPI(title='Document Intelligence Platform', version='0.1.0')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)


@app.middleware('http')
async def request_logging_middleware(request: Request, call_next: Callable):
    start = time()
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    request.state.user_id = None
    request.state.document_id = None

    try:
        response = await call_next(request)
        latency_ms = round((time() - start) * 1000, 2)
        status_code = response.status_code
        logger.info(
            f'{request.method} {request.url.path} {status_code} {latency_ms}ms (request_id={request_id})'
        )
        return response
    except Exception:
        latency_ms = round((time() - start) * 1000, 2)
        logger.exception(
            f'{request.method} {request.url.path} 500 {latency_ms}ms (request_id={request_id})'
        )
        raise


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.status_code,
        content={'detail': exc.detail, 'error': exc.__class__.__name__},
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    detail = exc.detail if isinstance(exc.detail, str) else 'HTTP error'
    return JSONResponse(status_code=exc.status_code, content={'detail': detail, 'error': 'HTTPException'})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=400, content={'detail': exc.errors(), 'error': 'ValidationError'})


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, 'request_id', 'unknown')
    logger.exception(f'unhandled error (request_id={request_id})')
    return JSONResponse(status_code=500, content={'detail': 'Internal server error.', 'error': 'InternalServerError'})


app.include_router(health_router)
app.include_router(auth_router)
app.include_router(documents_router)
app.include_router(conversations_router)


@app.get('/')
async def root() -> dict[str, str]:
    return {'message': 'Document Intelligence Platform API'}
