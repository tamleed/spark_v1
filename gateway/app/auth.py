from __future__ import annotations

import os

from fastapi import Header, HTTPException, Request, status


PUBLIC_PATHS = {"/health"}


def _required_key(admin: bool = False) -> str:
    if admin:
        return os.getenv("ADMIN_API_KEY") or os.getenv("GATEWAY_API_KEY", "")
    return os.getenv("GATEWAY_API_KEY", "")


def require_api_key(request: Request, x_api_key: str = Header(default="")) -> None:
    if request.url.path in PUBLIC_PATHS:
        return
    expected = _required_key(admin=request.url.path.startswith("/admin") or request.url.path in {"/queue", "/status"})
    if not expected:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="API key is not configured")
    if x_api_key != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
