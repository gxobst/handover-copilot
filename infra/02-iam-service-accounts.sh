#!/usr/bin/env bash
# ==============================================================================
# 02-iam-service-accounts.sh - Provision Service Accounts and IAM Roles
# Idempotent: safe to run multiple times.
# ==============================================================================
set -euo pipefail

PROJECT_ID="${GCP_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
if [[ -z "${PROJECT_ID}" ]]; then
  echo "ERROR: GCP_PROJECT is not set and could not be determined from gcloud config." >&2
  exit 1
fi

DEPLOYER_SA="handover-deployer"
RUNTIME_SA="handover-runtime"
DEPLOYER_EMAIL="${DEPLOYER_SA}@${PROJECT_ID}.iam.gserviceaccount.com"
RUNTIME_EMAIL="${RUNTIME_SA}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "==> Configuring IAM Service Accounts for project '${PROJECT_ID}'..."

# 1. Provision handover-deployer service account
if gcloud iam service-accounts describe "${DEPLOYER_EMAIL}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo "Service account '${DEPLOYER_EMAIL}' already exists."
else
  echo "Creating service account '${DEPLOYER_EMAIL}'..."
  gcloud iam service-accounts create "${DEPLOYER_SA}" \
    --display-name="Shift Handover CI/CD Deployer" \
    --project="${PROJECT_ID}"
fi

# 2. Provision handover-runtime service account
if gcloud iam service-accounts describe "${RUNTIME_EMAIL}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo "Service account '${RUNTIME_EMAIL}' already exists."
else
  echo "Creating service account '${RUNTIME_EMAIL}'..."
  gcloud iam service-accounts create "${RUNTIME_SA}" \
    --display-name="Shift Handover Cloud Run Runtime" \
    --project="${PROJECT_ID}"
fi

# 3. Assign roles to handover-deployer
DEPLOYER_ROLES=(
  "roles/run.admin"
  "roles/artifactregistry.writer"
  "roles/iam.serviceAccountUser"
  "roles/run.developer"
)

echo "Assigning roles to '${DEPLOYER_EMAIL}'..."
for role in "${DEPLOYER_ROLES[@]}"; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${DEPLOYER_EMAIL}" \
    --role="${role}" \
    --condition=None \
    --quiet >/dev/null
done

# 4. Assign roles to handover-runtime
RUNTIME_ROLES=(
  "roles/aiplatform.user"
  "roles/secretmanager.secretAccessor"
  "roles/alloydb.client"
  "roles/alloydb.databaseUser"
  "roles/cloudsql.client"
)

echo "Assigning roles to '${RUNTIME_EMAIL}'..."
for role in "${RUNTIME_ROLES[@]}"; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${RUNTIME_EMAIL}" \
    --role="${role}" \
    --condition=None \
    --quiet >/dev/null
done

# 5. Allow deployer to act as runtime service account
echo "Allowing '${DEPLOYER_EMAIL}' to impersonate '${RUNTIME_EMAIL}'..."
gcloud iam service-accounts add-iam-policy-binding "${RUNTIME_EMAIL}" \
  --member="serviceAccount:${DEPLOYER_EMAIL}" \
  --role="roles/iam.serviceAccountUser" \
  --project="${PROJECT_ID}" \
  --quiet >/dev/null

echo "==> Service accounts and IAM permissions configured successfully."
