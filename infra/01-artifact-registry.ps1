# 01-artifact-registry.ps1 - Provision Artifact Registry docker repository
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectId = if ($env:GCP_PROJECT) { $env:GCP_PROJECT } else { (gcloud.cmd config get-value project) }
$Region = if ($env:GCP_REGION) { $env:GCP_REGION } else { "europe-west2" }
$Repo = if ($env:ARTIFACT_REPO) { $env:ARTIFACT_REPO } else { "handover" }
$PolicyFile = Join-Path $ScriptDir "cleanup-policy.json"

Write-Host "==> Checking repository $Repo in $Region..."
$exists = & gcloud.cmd artifacts repositories describe $Repo --location=$Region --project=$ProjectId 2>$null
if (-not $exists) {
    Write-Host "Creating repository $Repo..."
    & gcloud.cmd artifacts repositories create $Repo --repository-format=docker --location=$Region --project=$ProjectId --description="Shift Handover Copilot Container Images"
}
Write-Host "Setting cleanup policies on $Repo..."
& gcloud.cmd artifacts repositories set-cleanup-policies $Repo --location=$Region --project=$ProjectId --policy=$PolicyFile --no-dry-run
Write-Host "==> Repository $Repo configured."
