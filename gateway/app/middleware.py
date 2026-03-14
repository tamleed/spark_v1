from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque
from typing import Deque, Dict

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-Id", str(uuid.uuid4()))
        request.state.request_id = request_id
        start = time.time()
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        response.headers["X-Process-Time"] = f"{time.time() - start:.3f}"
        return response


class SimpleRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_minute: int = 60):
        super().__init__(app)
        self.rpm = requests_per_minute
        self.events: Dict[str, Deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):
        key = request.headers.get("X-API-Key") or request.client.host
        now = time.time()
        bucket = self.events[key]
        while bucket and bucket[0] < now - 60:
            bucket.popleft()
        if len(bucket) >= self.rpm:
            return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429)
        bucket.append(now)
        return await call_next(request)
