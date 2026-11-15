#!/usr/bin/env bash
# ==============================================================================
# 03-wif.sh - Configure Workload Identity Federation for GitHub Actions
# Idempotent: safe to run multiple times.
# ==============================================================================
set -euo pipefail

PROJECT_ID="${GCP_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
if [[ -z "${PROJECT_ID}" ]]; then
  echo "ERROR: GCP_PROJECT is not set and could not be determined from gcloud config." >&2
  exit 1
fi

PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format="value(projectNumber)")"
REPO="${GITHUB_REPOSITORY:-gxobst/handover-copilot}"
POOL_ID="github-pool"
PROVIDER_ID="github-provider"
DEPLOYER_EMAIL="handover-deployer@${PROJECT_ID}.iam.gserviceaccount.com"

echo "==> Configuring Workload Identity Federation for '${REPO}' in project '${PROJECT_ID}' (${PROJECT_NUMBER})..."

# 1. Create or update Workload Identity Pool
if gcloud iam workload-identity-pools describe "${POOL_ID}" --location="global" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo "Workload Identity Pool '${POOL_ID}' already exists."
else
  echo "Creating Workload Identity Pool '${POOL_ID}'..."
  gcloud iam workload-identity-pools create "${POOL_ID}" \
    --location="global" \
    --display-name="GitHub Actions Pool" \
    --project="${PROJECT_ID}"
fi

# 2. Create or update OIDC Provider
if gcloud iam workload-identity-pools providers describe "${PROVIDER_ID}" \
    --workload-identity-pool="${POOL_ID}" \
    --location="global" \
    --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo "Workload Identity Provider '${PROVIDER_ID}' already exists."
else
  echo "Creating Workload Identity Provider '${PROVIDER_ID}'..."
  gcloud iam workload-identity-pools providers create-oidc "${PROVIDER_ID}" \
    --workload-identity-pool="${POOL_ID}" \
    --location="global" \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner" \
    --attribute-condition="assertion.repository == '${REPO}'" \
    --project="${PROJECT_ID}"
fi

# 3. Allow GitHub Actions from the repo to impersonate handover-deployer
MEMBER_PRINCIPAL="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/attribute.repository/${REPO}"

echo "Granting roles/iam.workloadIdentityUser to GitHub repository '${REPO}' on '${DEPLOYER_EMAIL}'..."
gcloud iam service-accounts add-iam-policy-binding "${DEPLOYER_EMAIL}" \
  --role="roles/iam.workloadIdentityUser" \
  --member="${MEMBER_PRINCIPAL}" \
  --project="${PROJECT_ID}" \
  --quiet >/dev/null

WIF_PROVIDER_NAME="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/providers/${PROVIDER_ID}"

echo "==> Workload Identity Federation configured successfully."
echo "WIF Provider: ${WIF_PROVIDER_NAME}"
echo "Deployer Service Account: ${DEPLOYER_EMAIL}"
