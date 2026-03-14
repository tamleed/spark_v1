from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request

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
    st = request.app.state.switcher.state
    q = get_queue(request.app.state.gateway_cfg)
    uptime = int(time.time() - request.app.state.started_at)
    return {
        "active_model": st.active_model,
        "switching": st.switching,
        "backend_state": st.backend_state,
        "queue_length": q.count,
        "uptime": uptime,
    }


@router.get("/queue")
def queue_status(request: Request):
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
    models = [m["name"] for m in request.app.state.models_cfg["models"]]
    if body.model not in models:
        raise HTTPException(400, "unknown model")

    q = get_queue(request.app.state.gateway_cfg)
    st = request.app.state.switcher.state
    if q.count == 0 and not st.switching:
        job = enqueue_chat_job(request.app.state.gateway_cfg, {
            "model": body.model,
            "messages": [{"role": "user", "content": "ping"}],
            "temperature": 0,
            "max_tokens": 1,
            "stream": False,
        }, admin=True)
        return {"mode": "queued_admin_job", "job_id": job.id}

    job = enqueue_chat_job(request.app.state.gateway_cfg, {
        "model": body.model,
        "messages": [{"role": "user", "content": "ping"}],
        "temperature": 0,
        "max_tokens": 1,
        "stream": False,
    }, admin=True)
    return {"mode": "queued_admin_job", "job_id": job.id}


@router.post("/admin/drain")
def drain(request: Request):
    request.app.state.drain_mode = True
    return {"drain_mode": True}
