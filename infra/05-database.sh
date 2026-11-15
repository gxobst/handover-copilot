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

# Ensure allowed PSC projects on instance
gcloud alloydb instances update "${INSTANCE_ID}" \
  --cluster="${CLUSTER_ID}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --allowed-psc-projects="${PROJECT_ID}" \
  --quiet >/dev/null 2>&1 || true

# Resolve connection info / PSC DNS
PSC_DNS="$(gcloud alloydb instances describe "${INSTANCE_ID}" --cluster="${CLUSTER_ID}" --region="${REGION}" --project="${PROJECT_ID}" --format="value(pscInstanceConfig.pscDnsName)" 2>/dev/null || echo "")"
echo "AlloyDB instance '${INSTANCE_ID}' is READY (PSC DNS: ${PSC_DNS})."

# Ensure consumer PSC IP and Forwarding Rule in VPC default
SA_LINK="$(gcloud alloydb instances describe "${INSTANCE_ID}" --cluster="${CLUSTER_ID}" --region="${REGION}" --project="${PROJECT_ID}" --format="value(pscInstanceConfig.serviceAttachmentLink)" 2>/dev/null || echo "")"
if ! gcloud compute addresses describe alloydb-psc-ip --region="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo "Creating consumer PSC IP 'alloydb-psc-ip'..."
  gcloud compute addresses create alloydb-psc-ip --region="${REGION}" --subnet="default" --project="${PROJECT_ID}"
fi
PSC_IP="$(gcloud compute addresses describe alloydb-psc-ip --region="${REGION}" --project="${PROJECT_ID}" --format="value(address)")"

if ! gcloud compute forwarding-rules describe alloydb-psc-forwarding-rule --region="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo "Creating consumer PSC forwarding rule 'alloydb-psc-forwarding-rule'..."
  gcloud compute forwarding-rules create alloydb-psc-forwarding-rule \
    --region="${REGION}" \
    --network="default" \
    --address="alloydb-psc-ip" \
    --target-service-attachment="${SA_LINK}" \
    --project="${PROJECT_ID}"
fi

# Ensure private Cloud DNS zone and record for PSC DNS resolution
gcloud services enable dns.googleapis.com --project="${PROJECT_ID}" --quiet >/dev/null 2>&1 || true
if ! gcloud dns managed-zones describe alloydb-psc-zone --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo "Creating private Cloud DNS zone 'alloydb-psc-zone'..."
  gcloud dns managed-zones create alloydb-psc-zone \
    --dns-name="alloydb-psc.goog." \
    --description="AlloyDB PSC Private Zone" \
    --visibility=private \
    --networks="default" \
    --project="${PROJECT_ID}"
fi

if ! gcloud dns record-sets list --zone=alloydb-psc-zone --project="${PROJECT_ID}" --format="value(name)" | grep -q "${PSC_DNS}"; then
  echo "Creating DNS record for ${PSC_DNS} -> ${PSC_IP}..."
  gcloud dns record-sets create "${PSC_DNS}" \
    --zone="alloydb-psc-zone" \
    --type="A" \
    --ttl=300 \
    --rrdatas="${PSC_IP}" \
    --project="${PROJECT_ID}"
fi

HOST="${PSC_DNS:-${PSC_IP}}"
DATABASE_URL_DEV="postgresql+psycopg://postgres:${DB_PASS}@${HOST}:5432/handover_dev?sslmode=require"
DATABASE_URL_PROD="postgresql+psycopg://postgres:${DB_PASS}@${HOST}:5432/handover_prod?sslmode=require"
DATABASE_URL="${DATABASE_URL_DEV}"

echo "Updating database connection secrets in Secret Manager..."
printf "%s" "${DATABASE_URL_DEV}" | gcloud secrets versions add "DATABASE_URL_DEV" --data-file=- --project="${PROJECT_ID}" >/dev/null 2>&1 || true
printf "%s" "${DATABASE_URL_PROD}" | gcloud secrets versions add "DATABASE_URL_PROD" --data-file=- --project="${PROJECT_ID}" >/dev/null 2>&1 || true
printf "%s" "${DATABASE_URL}" | gcloud secrets versions add "DATABASE_URL" --data-file=- --project="${PROJECT_ID}" >/dev/null 2>&1 || true

echo "==> AlloyDB cluster '${CLUSTER_ID}' / instance '${INSTANCE_ID}' configured successfully."
