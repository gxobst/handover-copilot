#!/usr/bin/env bash
# ==============================================================================
# 04-secret-manager.sh - Provision Secret Manager Secrets
# Idempotent: safe to run multiple times.
# ==============================================================================
set -euo pipefail

PROJECT_ID="${GCP_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
if [[ -z "${PROJECT_ID}" ]]; then
  echo "ERROR: GCP_PROJECT is not set and could not be determined from gcloud config." >&2
  exit 1
fi

RUNTIME_EMAIL="handover-runtime@${PROJECT_ID}.iam.gserviceaccount.com"

echo "==> Configuring Secret Manager secrets for project '${PROJECT_ID}'..."

# Helper function to create secret and add initial version if needed
ensure_secret() {
  local secret_name="$1"
  local default_val="$2"

  if gcloud secrets describe "${secret_name}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    echo "Secret '${secret_name}' already exists."
  else
    echo "Creating secret '${secret_name}'..."
    gcloud secrets create "${secret_name}" \
      --replication-policy="automatic" \
      --project="${PROJECT_ID}"
  fi

  # Check if secret has any versions
  local version_count
  version_count=$(gcloud secrets versions list "${secret_name}" --project="${PROJECT_ID}" --format="value(name)" 2>/dev/null | wc -l || echo 0)

  if [[ "${version_count}" -eq 0 ]]; then
    echo "Adding initial version for '${secret_name}'..."
    printf "%s" "${default_val}" | gcloud secrets versions add "${secret_name}" \
      --data-file=- \
      --project="${PROJECT_ID}" >/dev/null
  else
    echo "Secret '${secret_name}' already has ${version_count} version(s)."
  fi

  # Grant secretAccessor role to handover-runtime on the specific secret
  gcloud secrets add-iam-policy-binding "${secret_name}" \
    --member="serviceAccount:${RUNTIME_EMAIL}" \
    --role="roles/secretmanager.secretAccessor" \
    --project="${PROJECT_ID}" \
    --quiet >/dev/null
}

# 1. ADMIN_TOKEN
ADMIN_TOKEN_VAL="${ADMIN_TOKEN:-$(openssl rand -hex 24 2>/dev/null || python -c "import secrets; print(secrets.token_hex(24))" 2>/dev/null || echo "sec-admin-token-$(date +%s)")}"
ensure_secret "ADMIN_TOKEN" "${ADMIN_TOKEN_VAL}"

# 2. RELAY_WEBHOOK_TOKEN
RELAY_TOKEN_VAL="${RELAY_WEBHOOK_TOKEN:-$(openssl rand -hex 24 2>/dev/null || python -c "import secrets; print(secrets.token_hex(24))" 2>/dev/null || echo "sec-relay-token-$(date +%s)")}"
ensure_secret "RELAY_WEBHOOK_TOKEN" "${RELAY_TOKEN_VAL}"

# 3. DATABASE_URL
DEFAULT_DB_URL="${DATABASE_URL:-postgresql+psycopg://postgres:Yg0vCNCSfVTNpicWso_EBwDqvk4Vd9V1@/handover?host=/cloudsql/${PROJECT_ID}:europe-west2:handover-db}"
ensure_secret "DATABASE_URL" "${DEFAULT_DB_URL}"

# 4. GITHUB_DISPATCH_PAT
DEFAULT_PAT="${GITHUB_DISPATCH_PAT:-dummy-pat-to-be-updated}"
ensure_secret "GITHUB_DISPATCH_PAT" "${DEFAULT_PAT}"

echo "==> Secret Manager secrets provisioned and permissions granted to '${RUNTIME_EMAIL}'."
