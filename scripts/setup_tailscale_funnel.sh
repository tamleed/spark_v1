#!/usr/bin/env bash
set -euo pipefail
PORT="${TAILSCALE_FUNNEL_PORT:-443}"
TARGET="http://127.0.0.1:8000"
sudo tailscale funnel --bg --https="$PORT" "$TARGET"
URL=$(tailscale funnel status | awk '/https:/{print $2; exit}')
echo "Public API URL: ${URL:-<check tailscale funnel status>}"
echo "Disable: sudo tailscale funnel reset"

echo "This setup is suitable for dynamic/CGNAT ISP links: Funnel publishes via Tailscale domain (*.ts.net), no static public IP needed."
