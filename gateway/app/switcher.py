from __future__ import annotations

import asyncio
import os
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx

from .locks import combined_lock


@dataclass
class BackendState:
    active_model: Optional[str] = None
    backend_state: str = "stopped"
    switching: bool = False
    container_name: Optional[str] = None


class ModelSwitcher:
    def __init__(self, cfg: Dict[str, Any], models_cfg: Dict[str, Any]):
        self.cfg = cfg
        self.models_cfg = models_cfg
        self.state = BackendState()
        self._prefix = os.getenv("BACKEND_CONTAINER_NAME_PREFIX", "llm-backend")

    def get_active_model(self) -> Optional[str]:
        return self.state.active_model

    def _container_name(self, model_name: str) -> str:
        safe = model_name.replace("_", "-")
        return f"{self._prefix}-{safe}"

    def _run(self, cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, text=True, capture_output=True, check=check)

    def stop_current_model(self) -> None:
        if not self.state.container_name:
            self.state.active_model = None
            self.state.backend_state = "stopped"
            return

        graceful = int(self.cfg["switching"]["graceful_stop_timeout_sec"])
        name = self.state.container_name
        self._run(["docker", "stop", "--time", str(graceful), name], check=False)
        self._run(["docker", "kill", name], check=False)
        self._run(["docker", "rm", "-f", name], check=False)

        self.state.active_model = None
        self.state.container_name = None
        self.state.backend_state = "stopped"

    def start_model(self, model_name: str) -> None:
        model = next((m for m in self.models_cfg["models"] if m["name"] == model_name), None)
        if not model:
            raise ValueError(f"Unknown model: {model_name}")

        backend = model["backend"]
        port = str(backend.get("port", 8001))
        image = backend.get("image", "nvcr.io/nvidia/vllm:25.11-py3")
        container_name = self._container_name(model_name)
        source = model["source"]["value"]
        vllm_args = backend.get("vllm_args", [])

        docker_cfg = self.cfg.get("docker", {})
        docker_network_mode = os.getenv("DOCKER_NETWORK_MODE", docker_cfg.get("network_mode", "host"))
        runtime = os.getenv("DOCKER_RUNTIME", docker_cfg.get("runtime", "nvidia"))
        shm_size = os.getenv("DOCKER_SHM_SIZE", docker_cfg.get("shm_size", "16g"))
        ipc_mode = os.getenv("DOCKER_IPC_MODE", docker_cfg.get("ipc_mode", "host"))
        ulimit_memlock = str(docker_cfg.get("ulimits", {}).get("memlock", -1))
        ulimit_stack = str(docker_cfg.get("ulimits", {}).get("stack", 67108864))

        cmd = [
            "docker", "run", "-d",
            "--name", container_name,
            "--runtime", runtime,
            "--gpus", "all",
            "--network", docker_network_mode,
            "--ipc", ipc_mode,
            "--shm-size", shm_size,
            "--ulimit", f"memlock={ulimit_memlock}",
            "--ulimit", f"stack={ulimit_stack}",
            "-v", "/mnt/models:/mnt/models",
            "-v", "/var/lib/huggingface:/var/lib/huggingface",
            "-e", "HF_HOME=/var/lib/huggingface",
            "-e", "TRANSFORMERS_CACHE=/var/lib/huggingface",
            "-e", "NVIDIA_VISIBLE_DEVICES=all",
            "-e", "NVIDIA_DRIVER_CAPABILITIES=compute,utility",
        ]

        hf_token = os.getenv("HF_TOKEN")
        if hf_token:
            cmd.extend(["-e", f"HF_TOKEN={hf_token}"])

        cmd.append(image)
        cmd.extend(
            [
                "python",
                "-m",
                "vllm.entrypoints.openai.api_server",
                "--host",
                "0.0.0.0",
                "--port",
                port,
                "--model",
                source,
            ]
        )
        cmd.extend(vllm_args)

        proc = self._run(cmd, check=False)
        if proc.returncode != 0:
            raise RuntimeError(f"Failed to start backend: {proc.stderr.strip()}")

        self.state.container_name = container_name
        self.state.active_model = model_name
        self.state.backend_state = "starting"

    async def wait_backend_ready(self, model_name: str) -> None:
        model = next((m for m in self.models_cfg["models"] if m["name"] == model_name), None)
        if not model:
            raise ValueError(f"Unknown model: {model_name}")
        port = int(model["backend"].get("port", 8001))

        timeout = int(self.cfg["switching"]["backend_ready_timeout_sec"])
        deadline = time.time() + timeout
        url = f"http://127.0.0.1:{port}/v1/models"

        async with httpx.AsyncClient(timeout=5.0) as client:
            while time.time() < deadline:
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        self.state.backend_state = "ready"
                        return
                except Exception:
                    pass
                await asyncio.sleep(2)

        logs = ""
        if self.state.container_name:
            out = self._run(["docker", "logs", "--tail", "200", self.state.container_name], check=False)
            logs = out.stdout + "\n" + out.stderr
        self.state.backend_state = "failed"
        raise TimeoutError(f"Backend did not become ready in {timeout}s. Logs: {logs[:2000]}")

    async def ensure_model_active(self, model_name: str, file_lock_path: str) -> None:
        if self.state.active_model == model_name and self.state.backend_state == "ready":
            return

        self.state.switching = True
        try:
            async with combined_lock(file_lock_path):
                if self.state.active_model == model_name and self.state.backend_state == "ready":
                    return
                self.stop_current_model()
                self.start_model(model_name)
                await self.wait_backend_ready(model_name)
        finally:
            self.state.switching = False

    def force_cancel_running(self) -> None:
        self.stop_current_model()
