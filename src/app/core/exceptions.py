from __future__ import annotations

import logging
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas.response import ApiResponse

logger = logging.getLogger("app.core.exceptions")

def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        logger.warning("HTTPException %s %s -> %s", request.method, request.url.path, exc.detail)
        content = ApiResponse(code=exc.status_code, msg=str(exc.detail), data=None).model_dump()
        return JSONResponse(status_code=exc.status_code, content=content)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        logger.info("ValidationError on %s %s", request.method, request.url.path)
        content = ApiResponse(code=422, msg="validation_error", data=exc.errors()).model_dump()
        return JSONResponse(status_code=422, content=content)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        content = ApiResponse(code=500, msg="internal_server_error", data=None).model_dump()
        return JSONResponse(status_code=500, content=content)
