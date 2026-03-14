from __future__ import annotations

import os
import sys
from pathlib import Path

from redis import Redis
from rq import Connection, Queue, Worker

sys.path.append(str(Path(__file__).resolve().parents[1] / "gateway"))
from app.config import load_config  # noqa: E402


def main() -> None:
    cfg = load_config().gateway
    redis_url = os.getenv("REDIS_URL", cfg["redis"]["url"])
    conn = Redis.from_url(redis_url)

    with Connection(conn):
        queues = [Queue("admin"), Queue("default")]
        worker = Worker(queues, name="llm-switch-worker")
        worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
