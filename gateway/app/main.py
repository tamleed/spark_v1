from __future__ import annotations

import logging
import os
import time

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .auth import require_api_key
from .config import load_config
from .middleware import RequestContextMiddleware, SimpleRateLimitMiddleware
from .routes_admin import router as admin_router
from .routes_jobs import router as jobs_router
from .routes_openai import router as openai_router
from .switcher import ModelSwitcher

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI(title="LLM Switchboard", version="0.1.0", dependencies=[Depends(require_api_key)])
app.add_middleware(RequestContextMiddleware)
app.add_middleware(SimpleRateLimitMiddleware, requests_per_minute=120)

cfg = load_config()

cors_origins = cfg.gateway.get("security", {}).get("cors_allow_origins", [])
if cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.state.gateway_cfg = cfg.gateway
app.state.models_cfg = cfg.models
app.state.switcher = ModelSwitcher(cfg.gateway, cfg.models)
app.state.started_at = time.time()
app.state.current_job_id = None
app.state.drain_mode = False

app.include_router(openai_router)
app.include_router(jobs_router)
app.include_router(admin_router)


@app.get("/")
def root(request: Request):
    return {"service": "llm-switchboard", "request_id": getattr(request.state, "request_id", None)}
