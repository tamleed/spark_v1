from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import httpx

sys.path.append(str(Path(__file__).resolve().parents[1] / "gateway"))

from app.config import load_config  # noqa: E402
from app.model_registry import find_model  # noqa: E402
from app.models import JobStatus  # noqa: E402
from app.proxy import chat_completion  # noqa: E402
from app.switcher import ModelSwitcher  # noqa: E402

cfg_obj = load_config()
gateway_cfg = cfg_obj.gateway
models_cfg = cfg_obj.models
switcher = ModelSwitcher(gateway_cfg, models_cfg)


def execute_chat_job(payload: Dict[str, Any]):
    from rq import get_current_job

    job = get_current_job()
    job.meta["status"] = JobStatus.running.value
    job.meta["started_at"] = datetime.utcnow().isoformat()
    job.save_meta()

    model_name = payload["model"]
    inference_timeout = int(gateway_cfg.get("inference", {}).get("inference_timeout_sec", 240))

    async def _run():
        await switcher.ensure_model_active(model_name, gateway_cfg["locks"]["file_lock_path"])
        model = find_model(models_cfg, gateway_cfg, model_name)
        if model is None:
            raise ValueError(f"Unknown model: {model_name}")
        return await chat_completion(
            backend_port=int(model["backend"].get("port", 8001)),
            payload={k: v for k, v in payload.items() if k != "async"},
            timeout_sec=inference_timeout,
        )

    try:
        result = asyncio.run(asyncio.wait_for(_run(), timeout=inference_timeout))
        job.meta["status"] = JobStatus.succeeded.value
        job.meta["finished_at"] = datetime.utcnow().isoformat()
        job.save_meta()
        return result
    except (asyncio.TimeoutError, httpx.TimeoutException):
        switcher.force_cancel_running()
        job.meta["status"] = JobStatus.not_completed.value
        job.meta["error"] = "не выполнено: timeout waiting model response"
        job.meta["finished_at"] = datetime.utcnow().isoformat()
        job.save_meta()
        return {"status": "не выполнено", "reason": "timeout"}
    except Exception as exc:
        if "out of memory" in str(exc).lower() or "oom" in str(exc).lower():
            switcher.force_cancel_running()
            job.meta["status"] = JobStatus.not_completed.value
            job.meta["error"] = "не выполнено: GPU memory overflow, backend restarted"
            job.meta["finished_at"] = datetime.utcnow().isoformat()
            job.save_meta()
            return {"status": "не выполнено", "reason": "oom"}
        job.meta["status"] = JobStatus.failed.value
        job.meta["error"] = str(exc)
        job.meta["finished_at"] = datetime.utcnow().isoformat()
        job.save_meta()
        raise
