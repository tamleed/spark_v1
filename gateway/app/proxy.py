from __future__ import annotations

from typing import Any, Dict

import httpx


async def chat_completion(backend_port: int, payload: Dict[str, Any], timeout_sec: int) -> Dict[str, Any]:
    url = f"http://127.0.0.1:{backend_port}/v1/chat/completions"
    async with httpx.AsyncClient(timeout=timeout_sec) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()
