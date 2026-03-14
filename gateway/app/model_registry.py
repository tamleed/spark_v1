from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List


DEFAULT_DISCOVERY_DIRS = ["/opt/llm-switchboard/models", "/opt/llm-switchboard/model", "/mnt/models"]


def _dirs_from_env() -> List[str]:
    raw = os.getenv("MODEL_DISCOVERY_DIRS", "")
    if not raw.strip():
        return DEFAULT_DISCOVERY_DIRS
    return [d.strip() for d in raw.split(":") if d.strip()]


def discover_local_models(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    docker_cfg = cfg.get("docker", {})
    default_image = os.getenv("VLLM_IMAGE", "nvcr.io/nvidia/vllm:25.11-py3")
    default_port = int(cfg.get("inference_backend", {}).get("default_port", 8001))
    default_vllm_args = cfg.get("inference_backend", {}).get("default_vllm_args", ["--dtype", "bfloat16", "--max-model-len", "8192"])

    models: List[Dict[str, Any]] = []
    seen = set()
    for base in _dirs_from_env():
        p = Path(base)
        if not p.exists() or not p.is_dir():
            continue
        for child in sorted(p.iterdir()):
            if not child.is_dir():
                continue
            name = child.name
            if name in seen:
                continue
            seen.add(name)
            models.append(
                {
                    "name": name,
                    "source": {"type": "local_path", "value": str(child)},
                    "backend": {
                        "image": default_image,
                        "port": default_port,
                        "vllm_args": list(default_vllm_args),
                    },
                    "resources": {
                        "hf_cache_dir": "/var/lib/huggingface",
                        "models_dir": str(p),
                    },
                    "notes": "Auto-discovered local model directory",
                }
            )
    return models


def build_model_list(models_cfg: Dict[str, Any], gateway_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    configured = models_cfg.get("models", [])
    configured_names = {m.get("name") for m in configured}
    discovered = [m for m in discover_local_models(gateway_cfg) if m["name"] not in configured_names]
    return configured + discovered


def find_model(models_cfg: Dict[str, Any], gateway_cfg: Dict[str, Any], model_name: str) -> Dict[str, Any] | None:
    for model in build_model_list(models_cfg, gateway_cfg):
        if model.get("name") == model_name:
            return model
    return None
