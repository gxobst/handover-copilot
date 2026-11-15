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
JOB_NAME="handover-migrate"
RUNTIME_EMAIL="handover-runtime@${PROJECT_ID}.iam.gserviceaccount.com"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "ERROR: GCP_PROJECT is not set and could not be determined from gcloud config." >&2
  exit 1
fi

echo "==> Configuring Cloud Run Job '${JOB_NAME}' in '${REGION}' (project: ${PROJECT_ID})..."

COMMON_FLAGS=(
  "--image=${IMAGE_URI}"
  "--region=${REGION}"
  "--project=${PROJECT_ID}"
  "--service-account=${RUNTIME_EMAIL}"
  "--set-secrets=DATABASE_URL=DATABASE_URL:latest"
  "--clear-cloudsql-instances"
  "--command=uv"
  "--args=run,alembic,upgrade,head"
  "--max-retries=1"
  "--task-timeout=300s"
  "--cpu=1"
  "--memory=512Mi"
)

if gcloud run jobs describe "${JOB_NAME}" --region="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo "Updating existing Cloud Run Job '${JOB_NAME}'..."
  gcloud run jobs update "${JOB_NAME}" "${COMMON_FLAGS[@]}"
else
  echo "Creating Cloud Run Job '${JOB_NAME}'..."
  gcloud run jobs create "${JOB_NAME}" "${COMMON_FLAGS[@]}"
fi

echo "==> Cloud Run Job '${JOB_NAME}' configured successfully."
