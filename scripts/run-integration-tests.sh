#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:8000}"
TIMEOUT_SECONDS="${2:-60}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${ROOT_DIR}"

cleanup() {
    echo "[Orchestrator] Tearing down Docker Compose stack (docker compose down -v)..."
    docker compose down -v || true
}

trap cleanup EXIT

echo "================================================================="
echo "Starting Shift Handover Copilot Integration Test Orchestration"
echo "================================================================="

echo "[Orchestrator] Building and starting Docker Compose stack..."
docker compose up -d --build

echo "[Orchestrator] Polling ${BASE_URL}/api/healthz for healthy status..."
start_time=$(date +%s)
is_healthy=0

while [ $(( $(date +%s) - start_time )) -lt "${TIMEOUT_SECONDS}" ]; do
    if python3 -c "import urllib.request, json; resp = urllib.request.urlopen('${BASE_URL}/api/healthz', timeout=2); data = json.loads(resp.read().decode('utf-8')); assert data.get('status') == 'ok'" 2>/dev/null; then
        is_healthy=1
        echo "[Orchestrator] Container is healthy!"
        break
    fi
    sleep 2
done

if [ "${is_healthy}" -ne 1 ]; then
    echo "[ERROR] Container failed to report healthy within ${TIMEOUT_SECONDS} seconds" >&2
    docker compose logs
    exit 1
fi

echo "[Orchestrator] Executing integration test suite..."
python3 scripts/test_compose_integration.py --base-url "${BASE_URL}"

echo "================================================================="
echo "All integration test scenarios passed successfully!"
echo "================================================================="
