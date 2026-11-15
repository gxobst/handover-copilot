#!/usr/bin/env bash
# ==============================================================================
# 01-artifact-registry.sh - Provision Artifact Registry docker repository
# Idempotent: safe to run multiple times.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ID="${GCP_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${GCP_REGION:-europe-west2}"
REPO_NAME="${ARTIFACT_REPO:-handover}"
POLICY_FILE="${SCRIPT_DIR}/cleanup-policy.json"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "ERROR: GCP_PROJECT is not set and could not be determined from gcloud config." >&2
  exit 1
fi

echo "==> Configuring Artifact Registry repository '${REPO_NAME}' in '${REGION}' (project: ${PROJECT_ID})..."

# Check if repository already exists
if gcloud artifacts repositories describe "${REPO_NAME}" --location="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo "Repository '${REPO_NAME}' already exists."
else
  echo "Creating Docker repository '${REPO_NAME}' in '${REGION}'..."
  gcloud artifacts repositories create "${REPO_NAME}" \
    --repository-format=docker \
    --location="${REGION}" \
    --description="Shift Handover Copilot Container Images" \
    --project="${PROJECT_ID}"
fi

# Ensure cleanup policy exists
if [[ ! -f "${POLICY_FILE}" ]]; then
  cat <<'EOF' > "${POLICY_FILE}"
[
  {
    "name": "keep-5-most-recent",
    "action": {
      "type": "Keep"
    },
    "mostRecentVersions": {
      "keepCount": 5
    }
  },
  {
    "name": "delete-old-untagged",
    "action": {
      "type": "Delete"
    },
    "condition": {
      "tagState": "UNTAGGED",
      "olderThan": "604800s"
    }
  }
]
EOF
fi

echo "Setting cleanup policies on repository '${REPO_NAME}'..."
gcloud artifacts repositories set-cleanup-policies "${REPO_NAME}" \
  --location="${REGION}" \
  --project="${PROJECT_ID}" \
  --policy="${POLICY_FILE}" \
  --no-dry-run

echo "==> Artifact Registry repository '${REPO_NAME}' configured successfully."
