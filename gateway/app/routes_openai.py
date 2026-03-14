from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from .models import ChatCompletionRequest
from .proxy import chat_completion
from .queue import enqueue_chat_job, get_queue

router = APIRouter(prefix="/v1", tags=["openai"])


@router.get("/models")
def list_models(request: Request):
    models = request.app.state.models_cfg["models"]
    switcher = request.app.state.switcher
    return {
        "object": "list",
        "data": [{"id": m["name"], "object": "model"} for m in models],
        "active_model": switcher.state.active_model,
        "backend_state": switcher.state.backend_state,
    }


@router.post("/chat/completions")
async def create_chat_completion(body: ChatCompletionRequest, request: Request):
    cfg = request.app.state.gateway_cfg
    model_names = [m["name"] for m in request.app.state.models_cfg["models"]]
    if body.model not in model_names:
        raise HTTPException(400, f"Unknown model '{body.model}'")

    if body.stream and body.async_mode:
        raise HTTPException(400, "streaming not implemented in async mode yet")

    if body.max_tokens > int(cfg["policies"]["max_tokens_upper_bound"]):
        raise HTTPException(400, "max_tokens exceeds configured upper bound")

    if body.async_mode:
        job = enqueue_chat_job(cfg, body.model_dump(by_alias=True))
        return {
            "status": "accepted",
            "job_id": job.id,
            "status_url": f"/jobs/{job.id}",
        }

    q = get_queue(cfg)
    switcher = request.app.state.switcher
    if q.count > 0 or switcher.state.switching or switcher.state.active_model != body.model:
        raise HTTPException(409, "Queue not empty or model switch required; use async")

    model = next(m for m in request.app.state.models_cfg["models"] if m["name"] == body.model)
    result = await chat_completion(
        backend_port=int(model["backend"].get("port", 8001)),
        payload=body.model_dump(by_alias=True, exclude={"async_mode"}),
        timeout_sec=int(cfg["inference"]["inference_timeout_sec"]),
    )
    return result
