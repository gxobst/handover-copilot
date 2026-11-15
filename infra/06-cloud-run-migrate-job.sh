#!/usr/bin/env bash
# ==============================================================================
# 06-cloud-run-migrate-job.sh - Provision Cloud Run Database Migration Job
# Idempotent: creates or updates the job.
# Uses AlloyDB (or configured DATABASE_URL) without Cloud SQL proxies.
# ==============================================================================
set -euo pipefail

PROJECT_ID="${GCP_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${GCP_REGION:-europe-west2}"
REPO_NAME="${ARTIFACT_REPO:-handover}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/app:${IMAGE_TAG}"
# Target job can be specified via env var or 1st arg: "dev", "prod", or "all" (default)
TARGET_JOB="${1:-${MIGRATE_TARGET:-all}}"

provision_job() {
  local job_name="$1"
  local secret_name="$2"

  echo "==> Configuring Cloud Run Job '${job_name}' in '${REGION}' (secret: ${secret_name})..."

  local flags=(
    "--image=${IMAGE_URI}"
    "--region=${REGION}"
    "--project=${PROJECT_ID}"
    "--service-account=${RUNTIME_EMAIL}"
    "--network=default"
    "--subnet=default"
    "--vpc-egress=private-ranges-only"
    "--set-secrets=DATABASE_URL=${secret_name}:latest"
    "--clear-cloudsql-instances"
    "--command=uv"
    "--args=run,alembic,upgrade,head"
    "--max-retries=1"
    "--task-timeout=300s"
    "--cpu=1"
    "--memory=512Mi"
  )

  if gcloud run jobs describe "${job_name}" --region="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    echo "Updating existing Cloud Run Job '${job_name}'..."
    gcloud run jobs update "${job_name}" "${flags[@]}"
  else
    echo "Creating Cloud Run Job '${job_name}'..."
    gcloud run jobs create "${job_name}" "${flags[@]}"
  fi

  echo "Cloud Run Job '${job_name}' configured successfully."
}

if [[ "${TARGET_JOB}" == "dev" || "${TARGET_JOB}" == "all" ]]; then
  provision_job "handover-migrate-dev" "DATABASE_URL_DEV"
fi

if [[ "${TARGET_JOB}" == "prod" || "${TARGET_JOB}" == "all" ]]; then
  provision_job "handover-migrate-prod" "DATABASE_URL_PROD"
fi

# Also update legacy handover-migrate job pointing to DATABASE_URL_DEV for backwards compatibility
if [[ "${TARGET_JOB}" == "legacy" || "${TARGET_JOB}" == "all" ]]; then
  provision_job "handover-migrate" "DATABASE_URL_DEV"
fi

echo "==> Migration job configuration complete."
