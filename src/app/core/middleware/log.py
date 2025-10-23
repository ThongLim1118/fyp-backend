import logging
import time
import uuid
from fastapi import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)
FORWARDED_HEADERS = ("x-forwarded-for", "x-real-ip")

async def access_log(request: Request, call_next):
    start = time.perf_counter()
    req_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    client_ip = request.client.host if request.client else "-"
    for h in FORWARDED_HEADERS:
        v = request.headers.get(h)
        if v:
            client_ip = v.split(",")[0].strip()
            break

    response: Response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    response.headers.setdefault("X-Request-ID", req_id)

    logger.info(
        '%s %s %s %s %.2fms rid=%s',
        request.method, request.url.path, response.status_code,
        client_ip, elapsed_ms, req_id
    )
    return response
