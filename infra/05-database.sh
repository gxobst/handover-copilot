#!/usr/bin/env bash
# ==============================================================================
# 05-database.sh - Provision AlloyDB Express Database Persistence in europe-west2
# Matches plan.md §6 & §14: AlloyDB cluster with scale-to-zero compute (PostgreSQL 18).
# Idempotent: safe to run multiple times.
# ==============================================================================
set -euo pipefail

PROJECT_ID="${GCP_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${GCP_REGION:-europe-west2}"
CLUSTER_ID="${ALLOYDB_CLUSTER:-handover-cluster}"
INSTANCE_ID="${ALLOYDB_INSTANCE:-handover-primary}"
DB_PASS="${DB_PASSWORD:-Yg0vCNCSfVTNpicWso_EBwDqvk4Vd9V1}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "ERROR: GCP_PROJECT is not set and could not be determined from gcloud config." >&2
  exit 1
fi

echo "==> Configuring AlloyDB persistence in '${REGION}' (project: ${PROJECT_ID})..."

# Check if AlloyDB cluster exists
if gcloud alloydb clusters describe "${CLUSTER_ID}" --region="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo "AlloyDB cluster '${CLUSTER_ID}' already exists."
else
  echo "Creating AlloyDB cluster '${CLUSTER_ID}' (PostgreSQL 18) with Private Service Connect..."
  gcloud alloydb clusters create "${CLUSTER_ID}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --password="${DB_PASS}" \
    --database-version="POSTGRES_18" \
    --enable-private-service-connect
fi

# Check if primary instance exists
if gcloud alloydb instances describe "${INSTANCE_ID}" --cluster="${CLUSTER_ID}" --region="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo "AlloyDB primary instance '${INSTANCE_ID}' already exists."
else
  echo "Creating AlloyDB primary instance '${INSTANCE_ID}' (1 vCPU)..."
  gcloud alloydb instances create "${INSTANCE_ID}" \
    --cluster="${CLUSTER_ID}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --instance-type="PRIMARY" \
    --cpu-count=1
fi

echo "Waiting for AlloyDB primary instance '${INSTANCE_ID}' to become READY..."
while true; do
  STATE="$(gcloud alloydb instances describe "${INSTANCE_ID}" --cluster="${CLUSTER_ID}" --region="${REGION}" --project="${PROJECT_ID}" --format="value(state)" 2>/dev/null || echo "UNKNOWN")"
  echo "Current instance state: ${STATE}"
  if [[ "${STATE}" == "READY" ]]; then
    break
  fi
  sleep 15
done

# Resolve connection info / IP
IP_ADDRESS="$(gcloud alloydb instances describe "${INSTANCE_ID}" --cluster="${CLUSTER_ID}" --region="${REGION}" --project="${PROJECT_ID}" --format="value(ipAddress)" 2>/dev/null || echo "")"
echo "AlloyDB instance '${INSTANCE_ID}' is READY (IP: ${IP_ADDRESS})."

DATABASE_URL="postgresql+psycopg://postgres:${DB_PASS}@${IP_ADDRESS}:5432/postgres"

echo "Updating DATABASE_URL in Secret Manager..."
printf "%s" "${DATABASE_URL}" | gcloud secrets versions add "DATABASE_URL" \
  --data-file=- \
  --project="${PROJECT_ID}" >/dev/null

echo "==> AlloyDB cluster '${CLUSTER_ID}' / instance '${INSTANCE_ID}' configured successfully."
