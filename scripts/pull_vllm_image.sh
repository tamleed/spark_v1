#!/usr/bin/env bash
set -euo pipefail
IMAGE="${VLLM_IMAGE:-nvcr.io/nvidia/vllm:25.11-py3}"
docker pull "$IMAGE"
echo "[OK] Pulled $IMAGE"
