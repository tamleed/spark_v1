#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/opt/llm-switchboard"
PYTHON_BIN="${PYTHON_BIN:-python3}"
USER_NAME="${SUDO_USER:-$USER}"
UBUNTU_CODENAME="$(. /etc/os-release && echo ${UBUNTU_CODENAME})"

sudo mkdir -p "$ROOT_DIR" /var/lib/huggingface /mnt/models "$ROOT_DIR/models" "$ROOT_DIR/model" "/home/${USER_NAME}/work"
sudo chown -R "$USER_NAME":"$USER_NAME" "$ROOT_DIR" "/home/${USER_NAME}/work"

sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg lsb-release python3-venv python3-pip jq

if ! command -v docker >/dev/null 2>&1; then
  sudo apt-get install -y docker.io docker-compose-plugin
fi

# DGX Spark: configure NVIDIA Container Toolkit for Docker runtime.
if ! command -v nvidia-ctk >/dev/null 2>&1; then
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
    sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  curl -fsSL "https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list" | \
    sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
    sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null
  sudo apt-get update
  sudo apt-get install -y nvidia-container-toolkit
fi

sudo nvidia-ctk runtime configure --runtime=docker
if [ -f /opt/llm-switchboard/docker/daemon.json.dgx.example ]; then
  sudo cp /opt/llm-switchboard/docker/daemon.json.dgx.example /etc/docker/daemon.json
fi
sudo systemctl restart docker

if ! id -nG "$USER_NAME" | grep -qw docker; then
  sudo usermod -aG docker "$USER_NAME"
  echo "[INFO] Added ${USER_NAME} to docker group. Re-login or run: newgrp docker"
fi

cd "$ROOT_DIR"
$PYTHON_BIN -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "[OK] prerequisites installed for DGX Spark (Docker + NVIDIA runtime + Python envs)"
