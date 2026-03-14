from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request
from rq.command import send_stop_job_command

from .model_registry import find_model
from .models import JobCreateRequest, JobResponse, JobStatus
from .queue import enqueue_chat_job, fetch_job, queue_position, redis_conn

router = APIRouter(tags=["jobs"])


def _job_to_response(cfg: Dict[str, Any], job) -> JobResponse:
    meta = job.meta or {}
    status = meta.get("status", JobStatus.queued.value)
    return JobResponse(
        id=job.id,
        status=status,
        requested_model=meta.get("requested_model", "unknown"),
        created_at=datetime.fromisoformat(meta.get("created_at")),
        started_at=datetime.fromisoformat(meta["started_at"]) if meta.get("started_at") else None,
        finished_at=datetime.fromisoformat(meta["finished_at"]) if meta.get("finished_at") else None,
        queue_position=queue_position(cfg, job.id),
        progress=meta.get("progress"),
        error=meta.get("error"),
    )


@router.post("/jobs", response_model=JobResponse)
def create_job(body: JobCreateRequest, request: Request):
    cfg = request.app.state.gateway_cfg
    if find_model(request.app.state.models_cfg, cfg, body.model) is None:
        raise HTTPException(400, f"Unknown model '{body.model}'. Put model dir into /opt/llm-switchboard/models or /mnt/models.")
    if body.stream:
        raise HTTPException(400, "streaming not implemented in async mode yet")
    job = enqueue_chat_job(cfg, body.model_dump())
    return _job_to_response(cfg, job)


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str, request: Request):
    cfg = request.app.state.gateway_cfg
    job = fetch_job(cfg, job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return _job_to_response(cfg, job)


@router.get("/jobs/{job_id}/result")
def get_job_result(job_id: str, request: Request):
    cfg = request.app.state.gateway_cfg
    job = fetch_job(cfg, job_id)
    if not job:
        raise HTTPException(404, "job not found")
    status = job.meta.get("status")
    if status == JobStatus.succeeded.value:
        return job.result
    if status == JobStatus.failed.value:
        raise HTTPException(500, job.meta.get("error", "job failed"))
    if status == JobStatus.cancelled.value:
        raise HTTPException(409, "job cancelled")
    if status == JobStatus.not_completed.value:
        raise HTTPException(408, "не выполнено")
    raise HTTPException(202, "job not finished")


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, request: Request):
    cfg = request.app.state.gateway_cfg
    job = fetch_job(cfg, job_id)
    if not job:
        raise HTTPException(404, "job not found")

    status = job.meta.get("status", JobStatus.queued.value)
    if status in {JobStatus.succeeded.value, JobStatus.failed.value, JobStatus.cancelled.value, JobStatus.not_completed.value}:
        return {"id": job_id, "status": status}

    if job.get_status() == "queued":
        job.cancel()
        job.meta["status"] = JobStatus.cancelled.value
        job.meta["finished_at"] = datetime.utcnow().isoformat()
        job.save_meta()
        return {"id": job_id, "status": JobStatus.cancelled.value}

    try:
        send_stop_job_command(redis_conn(cfg), job_id)
    except Exception:
        pass
    request.app.state.switcher.force_cancel_running()
    job.meta["status"] = JobStatus.cancelled.value
    job.meta["finished_at"] = datetime.utcnow().isoformat()
    job.save_meta()
    return {"id": job_id, "status": JobStatus.cancelled.value}
