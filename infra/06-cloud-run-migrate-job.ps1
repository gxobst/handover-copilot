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
    [string]$TargetJob = "all"
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

function Provision-MigrateJob($job, $secret) {
    Write-Host "==> Configuring Cloud Run Job '$job' in '$Region' (secret: $secret)..."
    $jobCheck = & "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" run jobs describe $job --region=$Region --project=$ProjectId 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Updating existing Cloud Run Job '$job'..."
        & "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" run jobs update $job `
            --image=$imageUri `
            --region=$Region `
            --project=$ProjectId `
            --service-account=$runtimeEmail `
            --network="default" `
            --subnet="default" `
            --vpc-egress="private-ranges-only" `
            --set-secrets="DATABASE_URL=${secret}:latest" `
            --clear-cloudsql-instances `
            --command="uv" `
            --args="run,alembic,upgrade,head" `
            --max-retries=1 `
            --task-timeout="300s" `
            --cpu=1 `
            --memory="512Mi"
    } else {
        Write-Host "Creating Cloud Run Job '$job'..."
        & "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" run jobs create $job `
            --image=$imageUri `
            --region=$Region `
            --project=$ProjectId `
            --service-account=$runtimeEmail `
            --network="default" `
            --subnet="default" `
            --vpc-egress="private-ranges-only" `
            --set-secrets="DATABASE_URL=${secret}:latest" `
            --command="uv" `
            --args="run,alembic,upgrade,head" `
            --max-retries=1 `
            --task-timeout="300s" `
            --cpu=1 `
            --memory="512Mi"
    }
}

if ($TargetJob -eq "dev" -or $TargetJob -eq "all") {
    Provision-MigrateJob "handover-migrate-dev" "DATABASE_URL_DEV"
}

if ($TargetJob -eq "prod" -or $TargetJob -eq "all") {
    Provision-MigrateJob "handover-migrate-prod" "DATABASE_URL_PROD"
}

if ($TargetJob -eq "legacy" -or $TargetJob -eq "all") {
    Provision-MigrateJob "handover-migrate" "DATABASE_URL_DEV"
}

Write-Host "==> Migration job configuration complete."
