from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

sys.path.append(str(Path(__file__).resolve().parents[1] / "gateway"))

from app.config import load_config  # noqa: E402
from app.proxy import chat_completion  # noqa: E402
from app.switcher import ModelSwitcher  # noqa: E402
from app.models import JobStatus  # noqa: E402

cfg_obj = load_config()
gateway_cfg = cfg_obj.gateway
models_cfg = cfg_obj.models
switcher = ModelSwitcher(gateway_cfg, models_cfg)


def _find_model(name: str) -> Dict[str, Any]:
    return next(m for m in models_cfg["models"] if m["name"] == name)


def execute_chat_job(payload: Dict[str, Any]):
    from rq import get_current_job
    import asyncio

    job = get_current_job()
    job.meta["status"] = JobStatus.running.value
    job.meta["started_at"] = datetime.utcnow().isoformat()
    job.save_meta()

    model_name = payload["model"]

    async def _run():
        await switcher.ensure_model_active(model_name, gateway_cfg["locks"]["file_lock_path"])
        model = _find_model(model_name)
        return await chat_completion(
            backend_port=int(model["backend"].get("port", 8001)),
            payload={k: v for k, v in payload.items() if k != "async"},
            timeout_sec=int(gateway_cfg["inference"]["inference_timeout_sec"]),
        )

    try:
        result = asyncio.run(_run())
        job.meta["status"] = JobStatus.succeeded.value
        job.meta["finished_at"] = datetime.utcnow().isoformat()
        job.save_meta()
        return result
    except Exception as exc:
        job.meta["status"] = JobStatus.failed.value
        job.meta["error"] = str(exc)
        job.meta["finished_at"] = datetime.utcnow().isoformat()
        job.save_meta()
        raise
