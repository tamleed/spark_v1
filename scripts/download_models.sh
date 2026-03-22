#!/usr/bin/env bash
set -euo pipefail
MODELS_YAML_PATH="${MODELS_YAML_PATH:-/opt/llm-switchboard/configs/models.yaml}"
TARGET_ROOT="${MODELS_TARGET_ROOT:-/mnt/models}"

python3 - <<'PY'
import os, subprocess, yaml
from pathlib import Path

models_path = os.getenv("MODELS_YAML_PATH", "/opt/llm-switchboard/configs/models.yaml")
target_root = Path(os.getenv("MODELS_TARGET_ROOT", "/mnt/models"))

with open(models_path, "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f) or {}

ok, fail = [], []
for m in cfg.get("models", []):
    name = m.get("name")
    src = m.get("source", {})
    if src.get("type") != "huggingface_repo":
        print(f"[SKIP] {name}: source.type={src.get('type')}")
        continue
    repo = src.get("value", "")
    if repo.startswith("TODO") or not repo:
        print(f"[SKIP] {name}: placeholder repo")
        continue
    out_dir = target_root / name
    if out_dir.exists() and any(out_dir.iterdir()):
        print(f"[OK] {name}: already exists")
        ok.append(name)
        continue
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = ["huggingface-cli", "download", repo, "--local-dir", str(out_dir)]
    print("[RUN]", " ".join(cmd))
    try:
        subprocess.run(cmd, check=True)
        ok.append(name)
    except subprocess.CalledProcessError as exc:
        print(f"[FAIL] {name}: {exc}")
        fail.append(name)

print("\\nSUMMARY")
print("  downloaded/ready:", ok)
print("  failed:", fail)
if fail:
    raise SystemExit(1)
PY
