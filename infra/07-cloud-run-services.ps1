# 07-cloud-run-services.ps1 - Provision Cloud Run Services (dev, prod, relay)
$ErrorActionPreference = "Stop"
$ProjectId = if ($env:GCP_PROJECT) { $env:GCP_PROJECT } else { (gcloud.cmd config get-value project) }
$Region = if ($env:GCP_REGION) { $env:GCP_REGION } else { "europe-west2" }
$Repo = if ($env:ARTIFACT_REPO) { $env:ARTIFACT_REPO } else { "handover" }
$Tag = if ($env:IMAGE_TAG) { $env:IMAGE_TAG } else { "latest" }
$ImageUri = "$Region-docker.pkg.dev/$ProjectId/$Repo/app:$Tag"
$RuntimeEmail = "handover-runtime@$ProjectId.iam.gserviceaccount.com"
$CloudSqlConn = "$ProjectId`:$Region`:handover-db"

$services = @("handover-dev", "handover-prod", "handover-relay")

foreach ($svc in $services) {
    Write-Host "--- Provisioning Cloud Run service: $svc ---"
    $envName = if ($svc -eq "handover-prod") { "prod" } else { "dev" }
    $flags = @(
      "--image=$ImageUri",
      "--region=$Region",
      "--project=$ProjectId",
      "--service-account=$RuntimeEmail",
      "--min-instances=0",
      "--max-instances=2",
      "--cpu=1",
      "--memory=512Mi",
      "--timeout=120",
      "--port=8000",
      "--allow-unauthenticated",
      "--set-cloudsql-instances=$CloudSqlConn",
      "--set-secrets=DATABASE_URL=DATABASE_URL:latest,ADMIN_TOKEN=ADMIN_TOKEN:latest,RELAY_WEBHOOK_TOKEN=RELAY_WEBHOOK_TOKEN:latest",
      "--set-env-vars=APP_ENV=$envName,APP_VERSION=$Tag,GCP_PROJECT=$ProjectId,GCP_LOCATION=global,LLM_BACKEND=vertex,ACTIVE_MODEL=google/gemini-3.5-flash-lite,FALLBACK_MODEL=google/gemini-3.1-flash-lite,LLM_TIMEOUT_S=20"
    )
    $svcExists = & gcloud.cmd run services describe $svc --region=$Region --project=$ProjectId 2>$null
    if ($svcExists) {
        & gcloud.cmd run services update $svc @flags
    } else {
        & gcloud.cmd run deploy $svc @flags
    }
}
Write-Host "==> All Cloud Run services configured."
