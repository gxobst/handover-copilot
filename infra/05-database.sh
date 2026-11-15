#!/usr/bin/env bash
# ==============================================================================
# 05-database.sh - Provision Database Persistence in europe-west2
# Idempotent: safe to run multiple times.
# Supports Cloud SQL PostgreSQL (and AlloyDB Express where available).
# ==============================================================================
set -euo pipefail

PROJECT_ID="${GCP_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${GCP_REGION:-europe-west2}"
DB_INSTANCE_NAME="${DB_INSTANCE:-handover-db}"
DB_NAME="${DB_NAME:-handover}"
DB_USER="postgres"
DB_PASS="${DB_PASSWORD:-Yg0vCNCSfVTNpicWso_EBwDqvk4Vd9V1}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "ERROR: GCP_PROJECT is not set and could not be determined from gcloud config." >&2
  exit 1
fi

echo "==> Configuring database persistence in '${REGION}' (project: ${PROJECT_ID})..."

# Check if Cloud SQL instance exists
if gcloud sql instances describe "${DB_INSTANCE_NAME}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo "Cloud SQL instance '${DB_INSTANCE_NAME}' exists."
else
  echo "Provisioning Cloud SQL PostgreSQL instance '${DB_INSTANCE_NAME}' in '${REGION}'..."
  gcloud sql instances create "${DB_INSTANCE_NAME}" \
    --database-version="POSTGRES_16" \
    --tier="db-f1-micro" \
    --edition="ENTERPRISE" \
    --region="${REGION}" \
    --storage-size="10GB" \
    --storage-auto-increase \
    --root-password="${DB_PASS}" \
    --project="${PROJECT_ID}"
fi

# Wait until instance is RUNNABLE if it's still being created
echo "Waiting for instance '${DB_INSTANCE_NAME}' to become RUNNABLE..."
while true; do
  STATE="$(gcloud sql instances describe "${DB_INSTANCE_NAME}" --project="${PROJECT_ID}" --format="value(state)" 2>/dev/null || echo "UNKNOWN")"
  echo "Current instance state: ${STATE}"
  if [[ "${STATE}" == "RUNNABLE" ]]; then
    break
  fi
  sleep 10
done

# Ensure database 'handover' exists
if gcloud sql databases describe "${DB_NAME}" --instance="${DB_INSTANCE_NAME}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo "Database '${DB_NAME}' already exists on '${DB_INSTANCE_NAME}'."
else
  echo "Creating database '${DB_NAME}' on '${DB_INSTANCE_NAME}'..."
  gcloud sql databases create "${DB_NAME}" \
    --instance="${DB_INSTANCE_NAME}" \
    --project="${PROJECT_ID}"
fi

# Format connection string using Cloud Run's native Cloud SQL Unix socket
CONNECTION_NAME="${PROJECT_ID}:${REGION}:${DB_INSTANCE_NAME}"
DATABASE_URL="postgresql+psycopg://${DB_USER}:${DB_PASS}@/${DB_NAME}?host=/cloudsql/${CONNECTION_NAME}"

echo "Updating DATABASE_URL in Secret Manager..."
printf "%s" "${DATABASE_URL}" | gcloud secrets versions add "DATABASE_URL" \
  --data-file=- \
  --project="${PROJECT_ID}" >/dev/null

echo "==> Database '${DB_NAME}' on '${CONNECTION_NAME}' configured successfully."
