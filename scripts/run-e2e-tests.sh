#!/usr/bin/env bash
set -euo pipefail

BASE_URL="http://127.0.0.1:8000"
TIMEOUT_SECONDS=60
NO_TEARDOWN=0

for arg in "$@"; do
    case "$arg" in
        --no-teardown)
            NO_TEARDOWN=1
            ;;
        http*://*)
            BASE_URL="$arg"
            ;;
        [0-9]*)
            TIMEOUT_SECONDS="$arg"
            ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${ROOT_DIR}"

STARTED_BY_SCRIPT=0

cleanup() {
    if [ "${STARTED_BY_SCRIPT}" -eq 1 ] && [ "${NO_TEARDOWN}" -eq 0 ]; then
        echo "[E2E Orchestrator] Tearing down Docker Compose stack (docker compose down -v)..."
        docker compose down -v || true
    fi
}

trap cleanup EXIT

echo "================================================================="
echo "Starting Shift Handover Copilot End-to-End Test Orchestration"
echo "================================================================="

check_health() {
    python3 -c "import urllib.request, json; resp = urllib.request.urlopen('${BASE_URL}/api/healthz', timeout=2); data = json.loads(resp.read().decode('utf-8')); assert data.get('status') == 'ok'" 2>/dev/null
}

echo "[E2E Orchestrator] Checking if container stack is already healthy at ${BASE_URL}..."
if check_health; then
    echo "[E2E Orchestrator] Container stack is already running and healthy."
else
    echo "[E2E Orchestrator] Building and starting Docker Compose stack..."
    docker compose up -d --build
    STARTED_BY_SCRIPT=1

    echo "[E2E Orchestrator] Polling ${BASE_URL}/api/healthz for healthy status (timeout: ${TIMEOUT_SECONDS}s)..."
    start_time=$(date +%s)
    is_healthy=0

    while [ $(( $(date +%s) - start_time )) -lt "${TIMEOUT_SECONDS}" ]; do
        if check_health; then
            is_healthy=1
            echo "[E2E Orchestrator] Container is healthy!"
            break
        fi
        sleep 2
    done

    if [ "${is_healthy}" -ne 1 ]; then
        echo "[ERROR] Container failed to report healthy within ${TIMEOUT_SECONDS} seconds" >&2
        docker compose logs
        exit 1
    fi
fi

echo "[E2E Orchestrator] Running Playwright E2E test suite targeting ${BASE_URL}..."
export BASE_URL="${BASE_URL}"
npx playwright test -c e2e/playwright.config.ts

echo "================================================================="
echo "All Playwright end-to-end test journeys passed successfully!"
echo "================================================================="
