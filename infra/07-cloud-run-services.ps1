# ==============================================================================
# 07-cloud-run-services.ps1 - Provision Cloud Run Services (dev, prod, relay)
# Idempotent: creates or updates services.
# Uses AlloyDB / configured DATABASE_URL without Cloud SQL proxies.
# ==============================================================================
[CmdletBinding()]
param(
    [string]$ProjectId = $env:GCP_PROJECT,
    [string]$Region = "europe-west2",
    [string]$RepoName = "handover",
    [string]$ImageTag = "latest"
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

Write-Host "==> Configuring Cloud Run Services in '$Region' (project: $ProjectId)..."

$services = @("handover-dev", "handover-prod", "handover-relay")

foreach ($svc in $services) {
    Write-Host "--- Provisioning Cloud Run service: $svc ---"
    
    $envName = "dev"
    $secretSuffix = "DEV"
    if ($svc -eq "handover-prod") {
        $envName = "prod"
        $secretSuffix = "PROD"
    }

    $svcCheck = & "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" run services describe $svc --region=$Region --project=$ProjectId 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Updating service '$svc'..."
        & "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" run services update $svc `
            --image=$imageUri `
            --region=$Region `
            --project=$ProjectId `
            --service-account=$runtimeEmail `
            --network="default" `
            --subnet="default" `
            --vpc-egress="private-ranges-only" `
            --min-instances=0 `
            --max-instances=2 `
            --cpu=1 `
            --memory="512Mi" `
            --timeout=120 `
            --port=8000 `
            --allow-unauthenticated `
            --clear-cloudsql-instances `
            --set-secrets="DATABASE_URL=DATABASE_URL_${secretSuffix}:latest,ADMIN_TOKEN=ADMIN_TOKEN_${secretSuffix}:latest,RELAY_WEBHOOK_TOKEN=RELAY_WEBHOOK_TOKEN_${secretSuffix}:latest" `
            --set-env-vars="APP_ENV=${envName},APP_VERSION=${ImageTag},GCP_PROJECT=${ProjectId},GCP_LOCATION=global,LLM_BACKEND=vertex,ACTIVE_MODEL=google/gemini-3.5-flash-lite,FALLBACK_MODEL=google/gemini-3.1-flash-lite,LLM_TIMEOUT_S=20"
    } else {
        Write-Host "Deploying new service '$svc'..."
        & "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" run deploy $svc `
            --image=$imageUri `
            --region=$Region `
            --project=$ProjectId `
            --service-account=$runtimeEmail `
            --network="default" `
            --subnet="default" `
            --vpc-egress="private-ranges-only" `
            --min-instances=0 `
            --max-instances=2 `
            --cpu=1 `
            --memory="512Mi" `
            --timeout=120 `
            --port=8000 `
            --allow-unauthenticated `
            --clear-cloudsql-instances `
            --set-secrets="DATABASE_URL=DATABASE_URL_${secretSuffix}:latest,ADMIN_TOKEN=ADMIN_TOKEN_${secretSuffix}:latest,RELAY_WEBHOOK_TOKEN=RELAY_WEBHOOK_TOKEN_${secretSuffix}:latest" `
            --set-env-vars="APP_ENV=${envName},APP_VERSION=${ImageTag},GCP_PROJECT=${ProjectId},GCP_LOCATION=global,LLM_BACKEND=vertex,ACTIVE_MODEL=google/gemini-3.5-flash-lite,FALLBACK_MODEL=google/gemini-3.1-flash-lite,LLM_TIMEOUT_S=20"
    }

    $serviceUrl = & "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" run services describe $svc --region=$Region --project=$ProjectId --format="value(status.url)" 2>$null
    Write-Host "Service '$svc' ready at: $serviceUrl"
}

Write-Host "==> All Cloud Run services provisioned successfully."
