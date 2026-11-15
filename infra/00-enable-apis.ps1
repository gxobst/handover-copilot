# 00-enable-apis.ps1 - Enable required GCP APIs
$ErrorActionPreference = "Stop"
$ProjectId = if ($env:GCP_PROJECT) { $env:GCP_PROJECT } else { (gcloud.cmd config get-value project) }
Write-Host "==> Enabling GCP APIs for project: $ProjectId..."
& gcloud.cmd services enable `
  run.googleapis.com `
  artifactregistry.googleapis.com `
  secretmanager.googleapis.com `
  aiplatform.googleapis.com `
  alloydb.googleapis.com `
  sqladmin.googleapis.com `
  iam.googleapis.com `
  iamcredentials.googleapis.com `
  cloudresourcemanager.googleapis.com `
  compute.googleapis.com `
  --project=$ProjectId
Write-Host "==> APIs enabled."
