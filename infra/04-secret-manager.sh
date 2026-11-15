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

# 1. Environment-scoped secrets for Dev
DEV_DB_URL="${DATABASE_URL_DEV:-postgresql+psycopg://postgres:Yg0vCNCSfVTNpicWso_EBwDqvk4Vd9V1@f83b3631-742d-441d-b8bd-9cc88f57ddd6.166864bd-1d76-4532-828e-781c48d19b1f.europe-west2.alloydb-psc.goog.:5432/handover_dev?sslmode=require}"
ensure_secret "DATABASE_URL_DEV" "${DEV_DB_URL}"

DEV_ADMIN_TOKEN="${ADMIN_TOKEN_DEV:-$(openssl rand -hex 24 2>/dev/null || python -c "import secrets; print(secrets.token_hex(24))" 2>/dev/null || echo "sec-admin-dev-$(date +%s)")}"
ensure_secret "ADMIN_TOKEN_DEV" "${DEV_ADMIN_TOKEN}"

DEV_RELAY_TOKEN="${RELAY_WEBHOOK_TOKEN_DEV:-$(openssl rand -hex 24 2>/dev/null || python -c "import secrets; print(secrets.token_hex(24))" 2>/dev/null || echo "sec-relay-dev-$(date +%s)")}"
ensure_secret "RELAY_WEBHOOK_TOKEN_DEV" "${DEV_RELAY_TOKEN}"

# 2. Environment-scoped secrets for Prod
PROD_DB_URL="${DATABASE_URL_PROD:-postgresql+psycopg://postgres:Yg0vCNCSfVTNpicWso_EBwDqvk4Vd9V1@f83b3631-742d-441d-b8bd-9cc88f57ddd6.166864bd-1d76-4532-828e-781c48d19b1f.europe-west2.alloydb-psc.goog.:5432/handover_prod?sslmode=require}"
ensure_secret "DATABASE_URL_PROD" "${PROD_DB_URL}"

PROD_ADMIN_TOKEN="${ADMIN_TOKEN_PROD:-$(openssl rand -hex 24 2>/dev/null || python -c "import secrets; print(secrets.token_hex(24))" 2>/dev/null || echo "sec-admin-prod-$(date +%s)")}"
ensure_secret "ADMIN_TOKEN_PROD" "${PROD_ADMIN_TOKEN}"

PROD_RELAY_TOKEN="${RELAY_WEBHOOK_TOKEN_PROD:-$(openssl rand -hex 24 2>/dev/null || python -c "import secrets; print(secrets.token_hex(24))" 2>/dev/null || echo "sec-relay-prod-$(date +%s)")}"
ensure_secret "RELAY_WEBHOOK_TOKEN_PROD" "${PROD_RELAY_TOKEN}"

# 3. Backwards-compatible legacy secrets (aliases/fallbacks)
DEFAULT_DB_URL="${DATABASE_URL:-${DEV_DB_URL}}"
ensure_secret "DATABASE_URL" "${DEFAULT_DB_URL}"

LEGACY_ADMIN_TOKEN="${ADMIN_TOKEN:-${DEV_ADMIN_TOKEN}}"
ensure_secret "ADMIN_TOKEN" "${LEGACY_ADMIN_TOKEN}"

LEGACY_RELAY_TOKEN="${RELAY_WEBHOOK_TOKEN:-${DEV_RELAY_TOKEN}}"
ensure_secret "RELAY_WEBHOOK_TOKEN" "${LEGACY_RELAY_TOKEN}"

# 4. GITHUB_DISPATCH_PAT
DEFAULT_PAT="${GITHUB_DISPATCH_PAT:-dummy-pat-to-be-updated}"
ensure_secret "GITHUB_DISPATCH_PAT" "${DEFAULT_PAT}"

echo "==> Secret Manager secrets provisioned and permissions granted to '${RUNTIME_EMAIL}'."
