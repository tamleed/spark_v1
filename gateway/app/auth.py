from __future__ import annotations

import os
from typing import Set

from fastapi import Header, HTTPException, Request, status


def _allow_public_health() -> bool:
    return os.getenv("ALLOW_PUBLIC_HEALTH", "false").strip().lower() in {"1", "true", "yes", "on"}


def _parse_keys(multi_env: str, single_env: str) -> Set[str]:
    values = set()
    raw_multi = os.getenv(multi_env, "")
    for item in raw_multi.split(","):
        key = item.strip()
        if key:
            values.add(key)

    raw_single = os.getenv(single_env, "").strip()
    if raw_single:
        values.add(raw_single)
    return values


def _allowed_keys(admin: bool = False) -> Set[str]:
    if admin:
        admin_keys = _parse_keys("ADMIN_API_KEYS", "ADMIN_API_KEY")
        if admin_keys:
            return admin_keys
    return _parse_keys("GATEWAY_API_KEYS", "GATEWAY_API_KEY")


def require_api_key(request: Request, x_api_key: str = Header(default="")) -> None:
    if request.url.path == "/health" and _allow_public_health():
        return

    expected = _allowed_keys(admin=request.url.path.startswith("/admin") or request.url.path in {"/queue", "/status"})
    if not expected:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="API key is not configured")
    if x_api_key not in expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
