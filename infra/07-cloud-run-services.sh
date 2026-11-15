#!/usr/bin/env bash
# ==============================================================================
# 07-cloud-run-services.sh - Provision Cloud Run Services (dev, prod, relay)
# Idempotent: creates or updates services.
# Uses AlloyDB / configured DATABASE_URL without Cloud SQL proxies.
# ==============================================================================
set -euo pipefail

PROJECT_ID="${GCP_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${GCP_REGION:-europe-west2}"
REPO_NAME="${ARTIFACT_REPO:-handover}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/app:${IMAGE_TAG}"
RUNTIME_EMAIL="handover-runtime@${PROJECT_ID}.iam.gserviceaccount.com"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "ERROR: GCP_PROJECT is not set and could not be determined from gcloud config." >&2
  exit 1
fi

echo "==> Configuring Cloud Run Services in '${REGION}' (project: ${PROJECT_ID})..."

SERVICES=("handover-dev" "handover-prod" "handover-relay")

for svc in "${SERVICES[@]}"; do
  echo "--- Provisioning Cloud Run service: ${svc} ---"
  
  ENV_NAME="dev"
  SECRET_SUFFIX="DEV"
  if [[ "${svc}" == "handover-prod" ]]; then
    ENV_NAME="prod"
    SECRET_SUFFIX="PROD"
  fi

  COMMON_FLAGS=(
    "--image=${IMAGE_URI}"
    "--region=${REGION}"
    "--project=${PROJECT_ID}"
    "--service-account=${RUNTIME_EMAIL}"
    "--network=default"
    "--subnet=default"
    "--vpc-egress=private-ranges-only"
    "--min-instances=0"
    "--max-instances=2"
    "--cpu=1"
    "--memory=512Mi"
    "--timeout=120"
    "--port=8000"
    "--allow-unauthenticated"
    "--clear-cloudsql-instances"
    "--set-secrets=DATABASE_URL=DATABASE_URL_${SECRET_SUFFIX}:latest,ADMIN_TOKEN=ADMIN_TOKEN_${SECRET_SUFFIX}:latest,RELAY_WEBHOOK_TOKEN=RELAY_WEBHOOK_TOKEN_${SECRET_SUFFIX}:latest"
    "--set-env-vars=APP_ENV=${ENV_NAME},APP_VERSION=${IMAGE_TAG},GCP_PROJECT=${PROJECT_ID},GCP_LOCATION=global,LLM_BACKEND=vertex,ACTIVE_MODEL=google/gemini-3.5-flash-lite,FALLBACK_MODEL=google/gemini-3.1-flash-lite,LLM_TIMEOUT_S=20"
  )

  if gcloud run services describe "${svc}" --region="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    echo "Updating service '${svc}'..."
    gcloud run services update "${svc}" "${COMMON_FLAGS[@]}"
  else
    echo "Deploying new service '${svc}'..."
    gcloud run deploy "${svc}" "${COMMON_FLAGS[@]}"
  fi

  SERVICE_URL="$(gcloud run services describe "${svc}" --region="${REGION}" --project="${PROJECT_ID}" --format="value(status.url)")"
  echo "Service '${svc}' ready at: ${SERVICE_URL}"
done

echo "==> All Cloud Run services provisioned successfully."
