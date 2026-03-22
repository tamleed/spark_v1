#!/usr/bin/env bash
set -euo pipefail

echo "== tailscale status =="
tailscale status --peers=false || true

echo "== tailscale self =="
TS_JSON="$(tailscale status --json 2>/dev/null || true)"
if [ -n "$TS_JSON" ]; then
  TS_IP="$(echo "$TS_JSON" | jq -r '.Self.TailscaleIPs[0] // empty')"
  TS_DNS="$(echo "$TS_JSON" | jq -r '.Self.DNSName // empty')"
  echo "Tailscale IP: ${TS_IP:-unknown}"
  echo "Tailscale DNS: ${TS_DNS:-unknown}"
  echo "Note: static public ISP IP is NOT required; use Funnel (*.ts.net) or tailnet access."
fi

echo "== serve status =="
tailscale serve status || true

echo "== funnel status =="
tailscale funnel status || true
