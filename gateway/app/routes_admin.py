from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request

from .model_registry import build_model_list
from .models import AdminSwitchRequest
from .queue import enqueue_chat_job, get_queue, redis_conn

router = APIRouter(tags=["admin"])


@router.get("/health")
def health(request: Request):
    cfg = request.app.state.gateway_cfg
    try:
        redis_conn(cfg).ping()
        redis_ok = True
    except Exception:
        redis_ok = False
    return {"ok": True, "redis": redis_ok}


@router.get("/status")
def status(request: Request):
    request.app.state.switcher.sync_state_with_docker(check_readiness=True)
    st = request.app.state.switcher.state
    q = get_queue(request.app.state.gateway_cfg)
    uptime = int(time.time() - request.app.state.started_at)
    return {
        "active_model": st.active_model,
        "switching": st.switching,
        "backend_state": st.backend_state,
        "queue_length": q.count,
        "uptime": uptime,
        "containers_split": True,
    }


@router.get("/queue")
def queue_status(request: Request):
    request.app.state.switcher.sync_state_with_docker(check_readiness=False)
    st = request.app.state.switcher.state
    q = get_queue(request.app.state.gateway_cfg)
    current = request.app.state.current_job_id
    return {
        "queue_length": q.count,
        "current_job": current,
        "active_model": st.active_model,
        "switching": st.switching,
        "drain_mode": bool(request.app.state.drain_mode),
    }


@router.post("/admin/switch")
def manual_switch(body: AdminSwitchRequest, request: Request):
    models = [m["name"] for m in build_model_list(request.app.state.models_cfg, request.app.state.gateway_cfg)]
    if body.model not in models:
        raise HTTPException(400, "unknown model")

    job = enqueue_chat_job(
        request.app.state.gateway_cfg,
        {
            "model": body.model,
            "messages": [{"role": "user", "content": "ping"}],
            "temperature": 0,
            "max_tokens": 1,
            "stream": False,
        },
        admin=True,
    )
    return {"mode": "queued_admin_job", "job_id": job.id}


@router.post("/admin/drain")
def drain(request: Request):
    request.app.state.drain_mode = True
    return {"drain_mode": True}
