#!/usr/bin/env bash
set -euo pipefail
sudo tailscale serve --bg 8888 http://127.0.0.1:8888
tailscale serve status
echo "Jupyter is tailnet-only. Access from a device in your tailnet."
