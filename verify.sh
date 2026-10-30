#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export LOCAL_UID="${LOCAL_UID:-$(id -u)}"
export LOCAL_GID="${LOCAL_GID:-$(id -g)}"
mkdir -p artifacts
export LAB_RUN_ID="$(date -u +%Y%m%dT%H%M%S)-$$"
started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
collect() {
  docker compose logs --no-color --since "$started_at" gateway guardrails mock > artifacts/compose.log 2>&1 || true
  docker image inspect cr.agentgateway.dev/agentgateway:v1.7.0 > artifacts/gateway-image.json 2>/dev/null || true
  if [ -d "artifacts/runs/$LAB_RUN_ID" ]; then
    cp artifacts/compose.log artifacts/gateway-image.json "artifacts/runs/$LAB_RUN_ID/"
    cp gateway/config.yaml "artifacts/runs/$LAB_RUN_ID/gateway-config.yaml"
    docker compose cp guardrails:/app/test-reports "artifacts/runs/$LAB_RUN_ID/java-tests" >/dev/null 2>&1 || true
    docker compose images --format json > "artifacts/runs/$LAB_RUN_ID/compose-images.json" 2>/dev/null || true
  fi
}
trap collect EXIT
docker compose up --build -d
docker compose run --rm tests
