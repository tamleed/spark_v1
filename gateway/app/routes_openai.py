from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from .model_registry import build_model_list, find_model
from .models import ChatCompletionRequest
from .proxy import chat_completion
from .queue import enqueue_chat_job, get_queue

router = APIRouter(prefix="/v1", tags=["openai"])


@router.get("/models")
def list_models(request: Request):
    request.app.state.model_list = build_model_list(request.app.state.models_cfg, request.app.state.gateway_cfg)
    models = request.app.state.model_list
    switcher = request.app.state.switcher
    return {
        "object": "list",
        "data": [{"id": m["name"], "object": "model"} for m in models],
        "active_model": switcher.state.active_model,
        "backend_state": switcher.state.backend_state,
        "async_external_api": True,
    }


@router.post("/chat/completions")
async def create_chat_completion(body: ChatCompletionRequest, request: Request):
    cfg = request.app.state.gateway_cfg
    model = find_model(request.app.state.models_cfg, cfg, body.model)
    if model is None:
        raise HTTPException(400, f"Unknown model '{body.model}'. Put model dir into /opt/llm-switchboard/models or /mnt/models.")

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
            "result_url": f"/jobs/{job.id}/result",
        }

    q = get_queue(cfg)
    switcher = request.app.state.switcher
    if q.count > 0 or switcher.state.switching or switcher.state.active_model != body.model:
        raise HTTPException(409, "Queue not empty or model switch required; use async")

    backend_payload = body.model_dump(by_alias=True, exclude={"async_mode"})
    backend_payload["model"] = model["source"]["value"]
    result = await chat_completion(
        backend_port=int(model["backend"].get("port", 8001)),
        payload=backend_payload,
        timeout_sec=int(cfg["inference"]["inference_timeout_sec"]),
    )
    return result
