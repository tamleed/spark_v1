from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from filelock import FileLock


switch_lock = asyncio.Lock()


@asynccontextmanager
async def combined_lock(file_lock_path: str, timeout: int = 120):
    async with switch_lock:
        file_lock = FileLock(file_lock_path, timeout=timeout)
        file_lock.acquire()
        try:
            yield
        finally:
            file_lock.release()
