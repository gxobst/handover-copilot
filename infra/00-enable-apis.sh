#!/usr/bin/env bash
# ==============================================================================
# 00-enable-apis.sh - Enable required GCP APIs
# Idempotent: safe to run multiple times.
# ==============================================================================
set -euo pipefail

PROJECT_ID="${GCP_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
if [[ -z "${PROJECT_ID}" ]]; then
  echo "ERROR: GCP_PROJECT is not set and could not be determined from gcloud config." >&2
  exit 1
fi

echo "==> Enabling required GCP APIs for project: ${PROJECT_ID}..."
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  aiplatform.googleapis.com \
  alloydb.googleapis.com \
  sqladmin.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  cloudresourcemanager.googleapis.com \
  compute.googleapis.com \
  --project="${PROJECT_ID}"

echo "==> All required GCP APIs enabled successfully."
