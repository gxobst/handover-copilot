#!/usr/bin/env bash
# ==============================================================================
# 06-cloud-run.sh - Orchestrate Cloud Run Migration Job and Services Provisioning
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> [1/2] Configuring Cloud Run migration job..."
"${SCRIPT_DIR}/06-cloud-run-migrate-job.sh"

echo "==> [2/2] Configuring Cloud Run services..."
"${SCRIPT_DIR}/07-cloud-run-services.sh"

echo "==> Cloud Run job and services configuration complete."
