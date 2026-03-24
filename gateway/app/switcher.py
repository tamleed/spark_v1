from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx

from .locks import combined_lock
from .model_registry import DEFAULT_DISCOVERY_IMAGE, find_model


OOM_MARKERS = ["out of memory", "cuda out of memory", "cublas", "oom"]
MODEL_LABEL_KEY = "llm.switchboard.model"
SOURCE_LABEL_KEY = "llm.switchboard.source"


@dataclass
class BackendState:
    active_model: Optional[str] = None
    backend_state: str = "stopped"
    switching: bool = False
    container_name: Optional[str] = None
    last_error: Optional[str] = None


class ModelSwitcher:
    def __init__(self, cfg: Dict[str, Any], models_cfg: Dict[str, Any]):
        self.cfg = cfg
        self.models_cfg = models_cfg
        self.state = BackendState()
        self._prefix = os.getenv("BACKEND_CONTAINER_NAME_PREFIX", "llm-backend")
        self._docker_bin = os.getenv("DOCKER_BIN", shutil.which("docker") or "docker")

    def get_active_model(self) -> Optional[str]:
        return self.state.active_model

    def _container_name(self, model_name: str) -> str:
        return f"{self._prefix}-{model_name.replace('_', '-')}"

    def _run(self, cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, text=True, capture_output=True, check=check)

    def _docker(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return self._run([self._docker_bin, *args], check=check)

    def _docker_stdout(self, *args: str) -> str:
        proc = self._docker(*args, check=False)
        if proc.returncode != 0:
            return ""
        return (proc.stdout or "").strip()

    def _default_image(self) -> str:
        backend_cfg = self.cfg.get("inference_backend", {})
        return os.getenv("VLLM_IMAGE") or backend_cfg.get("default_image") or DEFAULT_DISCOVERY_IMAGE

    def _resolved_image(self, backend: Dict[str, Any]) -> str:
        image = backend.get("image") or self._default_image()
        if not image:
            raise RuntimeError(
                "No backend image configured. Set backend.image per model, VLLM_IMAGE, "
                "or inference_backend.default_image."
            )
        return image

    def _ensure_docker_access(self) -> None:
        if not shutil.which(self._docker_bin) and not os.path.exists(self._docker_bin):
            raise RuntimeError(
                f"Docker CLI '{self._docker_bin}' is not available inside the orchestrator container. "
                "Install docker-ce-cli and mount /var/run/docker.sock."
            )
        if not os.path.exists("/var/run/docker.sock"):
            raise RuntimeError("Docker socket /var/run/docker.sock is not mounted into the orchestrator container")
        probe = self._docker("version", "--format", "{{.Server.Version}}", check=False)
        if probe.returncode != 0:
            msg = probe.stderr.strip() or probe.stdout.strip() or "docker version failed"
            raise RuntimeError(f"Docker daemon is not reachable from the orchestrator container: {msg}")

    def stop_current_model(self) -> None:
        if not self.state.container_name:
            self.state.active_model = None
            self.state.backend_state = "stopped"
            return

        graceful = int(self.cfg["switching"]["graceful_stop_timeout_sec"])
        name = self.state.container_name
        self._docker("stop", "--time", str(graceful), name, check=False)
        self._docker("kill", name, check=False)
        self._docker("rm", "-f", name, check=False)

        self.state.active_model = None
        self.state.container_name = None
        self.state.backend_state = "stopped"

    def _container_model_from_name(self, container_name: str) -> Optional[str]:
        prefix = f"{self._prefix}-"
        if not container_name.startswith(prefix):
            return None
        return container_name[len(prefix) :].replace("-", "_")

    def _inspect_container(self, container_name: str) -> Optional[Dict[str, Any]]:
        raw = self._docker_stdout("inspect", container_name, "--format", "{{json .}}")
        if not raw:
            return None
        try:
            import json

            return json.loads(raw)
        except Exception:
            return None

    async def _is_backend_usable(self, model_name: str, source: str, port: int) -> bool:
        container_name = self._container_name(model_name)
        info = self._inspect_container(container_name)
        if not info:
            return False
        if not info.get("State", {}).get("Running"):
            return False
        url = f"http://127.0.0.1:{port}/v1/models"
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(url)
            if resp.status_code != 200:
                return False
            payload = resp.json()
            ids = [m.get("id") for m in payload.get("data", []) if isinstance(m, dict)]
            return source in ids
        except Exception:
            return False

    def sync_state_with_docker(self, check_readiness: bool = False) -> None:
        try:
            self._ensure_docker_access()
        except Exception as exc:
            self.state.last_error = str(exc)
            return

        names_raw = self._docker_stdout(
            "ps",
            "-a",
            "--filter",
            f"name=^/{self._prefix}-",
            "--format",
            "{{.Names}}",
        )
        names = [n.strip() for n in names_raw.splitlines() if n.strip()]
        if not names:
            self.state.active_model = None
            self.state.container_name = None
            self.state.backend_state = "stopped"
            return

        selected = self.state.container_name if self.state.container_name in names else names[0]
        info = self._inspect_container(selected)
        if not info:
            return
        labels = info.get("Config", {}).get("Labels", {}) or {}
        model_name = labels.get(MODEL_LABEL_KEY) or self._container_model_from_name(selected)
        running = bool(info.get("State", {}).get("Running"))

        self.state.container_name = selected
        self.state.active_model = model_name
        self.state.backend_state = "running" if running else "stopped"
        if not running:
            return

        if check_readiness and model_name:
            model = find_model(self.models_cfg, self.cfg, model_name)
            if model:
                port = int(model["backend"].get("port", 8001))
                source = model["source"]["value"]
                try:
                    # sync context: lightweight readiness probe without async machinery
                    with httpx.Client(timeout=2.0) as client:
                        resp = client.get(f"http://127.0.0.1:{port}/v1/models")
                    if resp.status_code == 200:
                        payload = resp.json()
                        ids = [m.get("id") for m in payload.get("data", []) if isinstance(m, dict)]
                        self.state.backend_state = "ready" if source in ids else "running"
                except Exception:
                    self.state.backend_state = "running"

    def start_model(self, model_name: str) -> None:
        model = find_model(self.models_cfg, self.cfg, model_name)
        if not model:
            raise ValueError(f"Unknown model: {model_name}")

        self._ensure_docker_access()

        backend = model["backend"]
        port = str(backend.get("port", 8001))
        image = self._resolved_image(backend)
        container_name = self._container_name(model_name)
        source = model["source"]["value"]
        vllm_args = backend.get("vllm_args", [])

        docker_cfg = self.cfg.get("docker", {})
        cmd = [
            self._docker_bin, "run", "-d",
            "--name", container_name,
            "--runtime", os.getenv("DOCKER_RUNTIME", docker_cfg.get("runtime", "nvidia")),
            "--gpus", os.getenv("DOCKER_GPUS", docker_cfg.get("gpus", "all")),
            "--network", os.getenv("DOCKER_NETWORK_MODE", docker_cfg.get("network_mode", "host")),
            "--ipc", os.getenv("DOCKER_IPC_MODE", docker_cfg.get("ipc_mode", "host")),
            "--shm-size", os.getenv("DOCKER_SHM_SIZE", docker_cfg.get("shm_size", "16g")),
            "--ulimit", f"memlock={docker_cfg.get('ulimits', {}).get('memlock', -1)}",
            "--ulimit", f"stack={docker_cfg.get('ulimits', {}).get('stack', 67108864)}",
            "-v", "/opt/llm-switchboard/models:/opt/llm-switchboard/models",
            "-v", "/opt/llm-switchboard/model:/opt/llm-switchboard/model",
            "-v", "/mnt/models:/mnt/models",
            "-v", "/var/lib/huggingface:/var/lib/huggingface",
            "-e", "HF_HOME=/var/lib/huggingface",
            "-e", "TRANSFORMERS_CACHE=/var/lib/huggingface",
            "-e", "NVIDIA_VISIBLE_DEVICES=all",
            "-e", "NVIDIA_DRIVER_CAPABILITIES=compute,utility",
            "--label", f"{MODEL_LABEL_KEY}={model_name}",
            "--label", f"{SOURCE_LABEL_KEY}={source}",
        ]

        hf_token = os.getenv("HF_TOKEN")
        if hf_token:
            cmd.extend(["-e", f"HF_TOKEN={hf_token}"])

        cmd.append(image)
        cmd.extend(["python", "-m", "vllm.entrypoints.openai.api_server", "--host", "0.0.0.0", "--port", port, "--model", source])
        cmd.extend(vllm_args)

        proc = self._run(cmd, check=False)
        if proc.returncode != 0:
            msg = proc.stderr.strip() or proc.stdout.strip()
            self.state.last_error = msg
            if self._is_oom(msg):
                self.stop_current_model()
                raise RuntimeError("GPU OOM while starting backend; model stopped and system is ready for next jobs")
            raise RuntimeError(f"Failed to start backend: {msg}")

        self.state.container_name = container_name
        self.state.active_model = model_name
        self.state.backend_state = "starting"
        self.state.last_error = None

    async def _prepare_target_container(self, model_name: str) -> bool:
        model = find_model(self.models_cfg, self.cfg, model_name)
        if not model:
            raise ValueError(f"Unknown model: {model_name}")
        container_name = self._container_name(model_name)
        source = model["source"]["value"]
        port = int(model["backend"].get("port", 8001))

        existing = self._inspect_container(container_name)
        if not existing:
            return False

        if await self._is_backend_usable(model_name, source, port):
            self.state.container_name = container_name
            self.state.active_model = model_name
            self.state.backend_state = "ready"
            self.state.last_error = None
            return True

        graceful = int(self.cfg["switching"]["graceful_stop_timeout_sec"])
        self._docker("stop", "--time", str(graceful), container_name, check=False)
        self._docker("rm", "-f", container_name, check=False)
        return False

    def _is_oom(self, text: str) -> bool:
        t = (text or "").lower()
        return any(marker in t for marker in OOM_MARKERS)

    async def wait_backend_ready(self, model_name: str) -> None:
        model = find_model(self.models_cfg, self.cfg, model_name)
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
            out = self._docker("logs", "--tail", "200", self.state.container_name, check=False)
            logs = (out.stdout or "") + "\n" + (out.stderr or "")
        self.state.backend_state = "failed"
        self.state.last_error = logs[:2000]
        if self._is_oom(logs):
            self.stop_current_model()
            raise RuntimeError("GPU OOM while loading model; backend stopped and queue can continue")
        raise TimeoutError(f"Backend did not become ready in {timeout}s. Logs: {logs[:2000]}")

    async def ensure_model_active(self, model_name: str, file_lock_path: str) -> None:
        self.sync_state_with_docker(check_readiness=True)
        if self.state.active_model == model_name and self.state.backend_state == "ready":
            return

        self.state.switching = True
        try:
            async with combined_lock(file_lock_path):
                self.sync_state_with_docker(check_readiness=True)
                if self.state.active_model == model_name and self.state.backend_state == "ready":
                    return
                if await self._prepare_target_container(model_name):
                    return
                if self.state.container_name and self.state.container_name != self._container_name(model_name):
                    self.stop_current_model()
                self.start_model(model_name)
                await self.wait_backend_ready(model_name)
        finally:
            self.state.switching = False

    def force_cancel_running(self) -> None:
        self.stop_current_model()
