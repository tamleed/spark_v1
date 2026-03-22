from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from redis import Redis
from rq import Queue
from rq.job import Job

from .models import JobStatus


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def redis_conn(cfg: Dict[str, Any]) -> Redis:
    return Redis.from_url(os.getenv("REDIS_URL", cfg["redis"]["url"]))


def get_queue(cfg: Dict[str, Any], name: str = "default") -> Queue:
    return Queue(name=name, connection=redis_conn(cfg), default_timeout=cfg["inference"]["inference_timeout_sec"])


def enqueue_chat_job(cfg: Dict[str, Any], payload: Dict[str, Any], admin: bool = False) -> Job:
    queue_name = "admin" if admin else "default"
    q = get_queue(cfg, queue_name)
    job_id = str(uuid.uuid4())
    meta = {
        "status": JobStatus.queued.value,
        "requested_model": payload["model"],
        "created_at": utc_now(),
    }
    return q.enqueue("worker.tasks.execute_chat_job", kwargs={"payload": payload}, job_id=job_id, meta=meta)


def fetch_job(cfg: Dict[str, Any], job_id: str) -> Optional[Job]:
    conn = redis_conn(cfg)
    try:
        return Job.fetch(job_id, connection=conn)
    except Exception:
        return None


def queue_position(cfg: Dict[str, Any], job_id: str) -> Optional[int]:
    q = get_queue(cfg)
    ids = q.job_ids
    if job_id in ids:
        return ids.index(job_id) + 1
    return None
