from __future__ import annotations

import os

from redis import Redis
from rq import Connection, Queue, Worker

from gateway.app.config import load_config


def main() -> None:
    cfg = load_config().gateway
    redis_url = os.getenv("REDIS_URL", cfg["redis"]["url"])
    worker_name = os.getenv("RQ_WORKER_NAME", "llm-switch-worker")
    conn = Redis.from_url(redis_url)

    with Connection(conn):
        queues = [Queue("admin"), Queue("default")]
        worker = Worker(queues, name=worker_name)
        worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
