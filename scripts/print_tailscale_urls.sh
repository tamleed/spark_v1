#!/usr/bin/env bash
set -euo pipefail
echo "== tailscale status =="
tailscale status --peers=false || true
echo "== serve status =="
tailscale serve status || true
echo "== funnel status =="
tailscale funnel status || true
