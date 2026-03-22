from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import yaml


@dataclass
class AppConfig:
    gateway: Dict[str, Any]
    models: Dict[str, Any]



def _read_yaml(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config() -> AppConfig:
    gateway_path = os.getenv("GATEWAY_YAML_PATH", "/opt/llm-switchboard/configs/gateway.yaml")
    models_path = os.getenv("MODELS_YAML_PATH", "/opt/llm-switchboard/configs/models.yaml")

    gateway = _read_yaml(gateway_path)
    models = _read_yaml(models_path)

    return AppConfig(gateway=gateway, models=models)


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def ensure_dirs(paths: list[str]) -> None:
    for p in paths:
        Path(p).mkdir(parents=True, exist_ok=True)
