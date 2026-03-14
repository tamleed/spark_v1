#!/usr/bin/env bash
set -euo pipefail
API_URL="${API_URL:-http://127.0.0.1:8000}"
API_KEY="${GATEWAY_API_KEY:-change_me}"

pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1"; exit 1; }

curl -fsS "$API_URL/health" >/dev/null && pass "health" || fail "health"
curl -fsS -H "X-API-Key: $API_KEY" "$API_URL/v1/models" >/dev/null && pass "models" || fail "models"

JOB1=$(curl -fsS -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"gpt-oss120","messages":[{"role":"user","content":"Say hi"}],"max_tokens":16}' \
  "$API_URL/v1/chat/completions" | jq -r .job_id)
[ -n "$JOB1" ] && pass "submit async job1" || fail "submit async job1"

for _ in {1..120}; do
  S=$(curl -fsS -H "X-API-Key: $API_KEY" "$API_URL/jobs/$JOB1" | jq -r .status)
  [[ "$S" =~ ^(succeeded|failed|cancelled)$ ]] && break
  sleep 2
done
[ "$S" = "succeeded" ] && pass "job1 done" || echo "WARN: job1 status=$S"

JOB2=$(curl -fsS -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"qwen3-30b","messages":[{"role":"user","content":"2+2?"}],"max_tokens":16}' \
  "$API_URL/v1/chat/completions" | jq -r .job_id)
[ -n "$JOB2" ] && pass "submit job2 for switch" || fail "submit job2"

curl -fsS -X POST -H "X-API-Key: $API_KEY" "$API_URL/jobs/$JOB2/cancel" >/dev/null && pass "cancel endpoint" || fail "cancel"
