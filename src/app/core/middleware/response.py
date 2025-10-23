import json
import logging
import time
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from app.schemas.response import ApiResponse

logger = logging.getLogger("app.middleware.response")

SKIP_PATH_PREFIXES = ("/docs", "/redoc", "/openapi.json", "/healthz")

def _already_unified(payload: Any) -> bool:
    return (
        isinstance(payload, dict)
        and "code" in payload
        and "msg" in payload
        and "data" in payload
    )

def _should_skip(request: Request, response: Response | None) -> bool:
    path = request.url.path
    if any(path.startswith(p) for p in SKIP_PATH_PREFIXES):
        return True
    if request.headers.get("X-Skip-Unify") == "1":
        return True
    if response is not None and response.headers.get("X-Skip-Unify") == "1":
        return True
    return False

async def unify_response(request: Request, call_next):
    start = time.perf_counter()
    response: Response = await call_next(request)
    # 先写入耗时头
    response.headers["X-Process-Time"] = f"{(time.perf_counter() - start) * 1000:.2f}ms"

    if _should_skip(request, response):
        return response

    if not isinstance(response, JSONResponse):
        return response

    # 消费响应体（StreamingResponse）
    body_bytes: bytes = getattr(response, "body", b"")
    if not body_bytes:
        # 空响应也统一成 {code,msg,data}
        return JSONResponse(
            content=ApiResponse(code=0, msg="ok", data=None).model_dump(),
            status_code=response.status_code,
            headers=dict(response.headers),
            background=response.background,
        )

    # 尝试解析 JSON
    try:
        payload = json.loads(body_bytes.decode("utf-8") or "null")
    except json.JSONDecodeError:
        return response

    if _already_unified(payload):
        return response

    unified = ApiResponse(code=0, msg="ok", data=payload).dict()
    return JSONResponse(
        content=unified,
        status_code=response.status_code,
        headers=dict(response.headers),   # 继承原头（含 X-Process-Time / X-Request-ID）
        background=response.background,
    )
