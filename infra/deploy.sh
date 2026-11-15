#!/usr/bin/env bash
# ==============================================================================
# deploy.sh - Unified Build, Push, Migrate, Deploy, and Verify Script
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

PROJECT_ID="${GCP_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${GCP_REGION:-europe-west2}"
REPO_NAME="${ARTIFACT_REPO:-handover}"
SERVICE_NAME="${TARGET_SERVICE:-handover-dev}"
RUNTIME_EMAIL="handover-runtime@${PROJECT_ID}.iam.gserviceaccount.com"
DB_INSTANCE_NAME="${DB_INSTANCE:-handover-db}"
CLOUDSQL_CONNECTION="${PROJECT_ID}:${REGION}:${DB_INSTANCE_NAME}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "ERROR: GCP_PROJECT is not set and could not be determined from gcloud config." >&2
  exit 1
fi

SHORT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo "manual")"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
TAG="${TIMESTAMP}-${SHORT_SHA}"

IMAGE_BASE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/app"
IMAGE_TAGGED="${IMAGE_BASE}:${TAG}"
IMAGE_LATEST="${IMAGE_BASE}:latest"

echo "=========================================================================="
echo " Starting Shift Handover Copilot Deployment"
echo " Project:   ${PROJECT_ID}"
echo " Region:    ${REGION}"
echo " Service:   ${SERVICE_NAME}"
echo " Image Tag: ${TAG}"
echo "=========================================================================="

# 1. Authenticate Docker with Artifact Registry
echo "==> Configuring Docker credentials for Artifact Registry..."
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

# 2. Build Container Image
echo "==> Building container image ${IMAGE_TAGGED}..."
docker build -t "${IMAGE_TAGGED}" -t "${IMAGE_LATEST}" -f "${ROOT_DIR}/Dockerfile" "${ROOT_DIR}"

# 3. Push Container Image to Artifact Registry
echo "==> Pushing container images to Artifact Registry..."
docker push "${IMAGE_TAGGED}"
docker push "${IMAGE_LATEST}"

# 4. Update and Execute Database Migration Job
ENV_NAME="dev"
SECRET_SUFFIX="DEV"
MIGRATE_JOB="handover-migrate-dev"
if [[ "${SERVICE_NAME}" == *"prod"* ]]; then
  ENV_NAME="prod"
  SECRET_SUFFIX="PROD"
  MIGRATE_JOB="handover-migrate-prod"
fi

echo "==> Ensuring migration jobs exist with image ${IMAGE_TAGGED}..."
IMAGE_TAG="${TAG}" "${SCRIPT_DIR}/06-cloud-run-migrate-job.sh" "${ENV_NAME}"

echo "==> Executing database migration job '${MIGRATE_JOB}'..."
gcloud run jobs execute "${MIGRATE_JOB}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --wait

# 5. Deploy Cloud Run Service
echo "==> Deploying Cloud Run service '${SERVICE_NAME}' (${ENV_NAME})..."

gcloud run deploy "${SERVICE_NAME}" \
  --image="${IMAGE_TAGGED}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --service-account="${RUNTIME_EMAIL}" \
  --network="default" \
  --subnet="default" \
  --vpc-egress="private-ranges-only" \
  --min-instances=0 \
  --max-instances=2 \
  --cpu=1 \
  --memory=512Mi \
  --timeout=120 \
  --port=8000 \
  --allow-unauthenticated \
  --clear-cloudsql-instances \
  --set-secrets="DATABASE_URL=DATABASE_URL_${SECRET_SUFFIX}:latest,ADMIN_TOKEN=ADMIN_TOKEN_${SECRET_SUFFIX}:latest,RELAY_WEBHOOK_TOKEN=RELAY_WEBHOOK_TOKEN_${SECRET_SUFFIX}:latest" \
  --set-env-vars="APP_ENV=${ENV_NAME},APP_VERSION=${TAG},GCP_PROJECT=${PROJECT_ID},GCP_LOCATION=global,LLM_BACKEND=vertex,ACTIVE_MODEL=google/gemini-3.5-flash-lite,FALLBACK_MODEL=google/gemini-3.1-flash-lite,LLM_TIMEOUT_S=20"

# 6. Verify Live Service Health
SERVICE_URL="$(gcloud run services describe "${SERVICE_NAME}" --region="${REGION}" --project="${PROJECT_ID}" --format="value(status.url)")"
echo "==> Service deployed. Public URL: ${SERVICE_URL}"

echo "==> Verifying live service health at ${SERVICE_URL}/api/healthz..."
HEALTH_STATUS=""
for i in {1..12}; do
  echo "Attempt $i: Checking ${SERVICE_URL}/api/healthz..."
  HTTP_CODE="$(curl -s -o /tmp/health_response.json -w "%{http_code}" "${SERVICE_URL}/api/healthz" || echo "000")"
  if [[ "${HTTP_CODE}" == "200" ]]; then
    HEALTH_STATUS="OK"
    cat /tmp/health_response.json
    echo ""
    break
  fi
  sleep 5
done

if [[ "${HEALTH_STATUS}" != "OK" ]]; then
  echo "ERROR: Health check failed with HTTP ${HTTP_CODE}" >&2
  exit 1
fi

echo "=========================================================================="
echo " Deployment and Verification Successful!"
echo " Service URL: ${SERVICE_URL}"
echo " Version:     ${TAG}"
echo "=========================================================================="
