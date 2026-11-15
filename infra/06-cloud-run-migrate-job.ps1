# ==============================================================================
# 06-cloud-run-migrate-job.ps1 - Provision Cloud Run Database Migration Job
# Idempotent: creates or updates the job.
# Uses AlloyDB (or configured DATABASE_URL) without Cloud SQL proxies.
# ==============================================================================
[CmdletBinding()]
param(
    [string]$ProjectId = $env:GCP_PROJECT,
    [string]$Region = "europe-west2",
    [string]$RepoName = "handover",
    [string]$ImageTag = "latest",
    [string]$JobName = "handover-migrate"
)

$ErrorActionPreference = "Stop"

if (-not $ProjectId) {
    $ProjectId = & "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" config get-value project 2>$null
}
if (-not $ProjectId) {
    Write-Error "ERROR: ProjectId is required and could not be determined from gcloud config."
}

$imageUri = "${Region}-docker.pkg.dev/${ProjectId}/${RepoName}/app:${ImageTag}"
$runtimeEmail = "handover-runtime@${ProjectId}.iam.gserviceaccount.com"

Write-Host "==> Configuring Cloud Run Job '$JobName' in '$Region' (project: $ProjectId)..."

$jobCheck = & "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" run jobs describe $JobName --region=$Region --project=$ProjectId 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "Updating existing Cloud Run Job '$JobName'..."
    & "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" run jobs update $JobName `
        --image=$imageUri `
        --region=$Region `
        --project=$ProjectId `
        --service-account=$runtimeEmail `
        --set-secrets="DATABASE_URL=DATABASE_URL:latest" `
        --clear-cloudsql-instances `
        --command="uv" `
        --args="run,alembic,upgrade,head" `
        --max-retries=1 `
        --task-timeout="300s" `
        --cpu=1 `
        --memory="512Mi"
} else {
    Write-Host "Creating Cloud Run Job '$JobName'..."
    & "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" run jobs create $JobName `
        --image=$imageUri `
        --region=$Region `
        --project=$ProjectId `
        --service-account=$runtimeEmail `
        --set-secrets="DATABASE_URL=DATABASE_URL:latest" `
        --command="uv" `
        --args="run,alembic,upgrade,head" `
        --max-retries=1 `
        --task-timeout="300s" `
        --cpu=1 `
        --memory="512Mi"
}

Write-Host "==> Cloud Run Job '$JobName' configured successfully."
