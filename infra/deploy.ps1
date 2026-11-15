# deploy.ps1 - Windows PowerShell Deploy Script
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent $ScriptDir
$ProjectId = if ($env:GCP_PROJECT) { $env:GCP_PROJECT } else { (gcloud.cmd config get-value project) }
$Region = if ($env:GCP_REGION) { $env:GCP_REGION } else { "europe-west2" }
$Repo = if ($env:ARTIFACT_REPO) { $env:ARTIFACT_REPO } else { "handover" }
$Service = if ($env:TARGET_SERVICE) { $env:TARGET_SERVICE } else { "handover-dev" }

$shortSha = (& git rev-parse --short HEAD).Trim()
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$tag = "$timestamp-$shortSha"

$imageTagged = "$Region-docker.pkg.dev/$ProjectId/$Repo/app:$tag"
$imageLatest = "$Region-docker.pkg.dev/$ProjectId/$Repo/app:latest"

Write-Host "==> [1/6] Authenticating Docker with Artifact Registry..."
& gcloud.cmd auth configure-docker "$Region-docker.pkg.dev" --quiet

Write-Host "==> [2/6] Building Docker image $imageTagged..."
docker build -t $imageTagged -t $imageLatest -f "$RootDir/Dockerfile" "$RootDir"

Write-Host "==> [3/6] Pushing Docker images..."
docker push $imageTagged
docker push $imageLatest

Write-Host "==> [4/6] Updating and executing migration job..."
$env:IMAGE_TAG = $tag
$envName = if ($Service -like "*prod*") { "prod" } else { "dev" }
$secretSuffix = if ($Service -like "*prod*") { "PROD" } else { "DEV" }
$migrateJob = if ($Service -like "*prod*") { "handover-migrate-prod" } else { "handover-migrate-dev" }

& "$ScriptDir/06-cloud-run-migrate-job.ps1" -TargetJob $envName
& gcloud.cmd run jobs execute $migrateJob --region=$Region --project=$ProjectId --wait

Write-Host "==> [5/6] Deploying Cloud Run service $Service ($envName)..."
$RuntimeEmail = "handover-runtime@$ProjectId.iam.gserviceaccount.com"

& gcloud.cmd run deploy $Service `
  --image=$imageTagged `
  --region=$Region `
  --project=$ProjectId `
  --service-account=$RuntimeEmail `
  --network="default" `
  --subnet="default" `
  --vpc-egress="private-ranges-only" `
  --min-instances=0 `
  --max-instances=2 `
  --cpu=1 `
  --memory=512Mi `
  --timeout=120 `
  --port=8000 `
  --allow-unauthenticated `
  --clear-cloudsql-instances `
  --set-secrets="DATABASE_URL=DATABASE_URL_${secretSuffix}:latest,ADMIN_TOKEN=ADMIN_TOKEN_${secretSuffix}:latest,RELAY_WEBHOOK_TOKEN=RELAY_WEBHOOK_TOKEN_${secretSuffix}:latest" `
  --set-env-vars="APP_ENV=$envName,APP_VERSION=$tag,GCP_PROJECT=$ProjectId,GCP_LOCATION=global,LLM_BACKEND=vertex,ACTIVE_MODEL=google/gemini-3.5-flash-lite,FALLBACK_MODEL=google/gemini-3.1-flash-lite,LLM_TIMEOUT_S=20"

$serviceUrl = (& gcloud.cmd run services describe $Service --region=$Region --project=$ProjectId --format="value(status.url)").Trim()
Write-Host "==> [6/6] Verifying live health check at $serviceUrl/api/healthz..."

$healthy = $false
for ($i = 1; $i -le 12; $i++) {
    Write-Host "Attempt $i checking $serviceUrl/api/healthz..."
    try {
        $res = Invoke-RestMethod -Uri "$serviceUrl/api/healthz" -Method Get -TimeoutSec 10
        if ($res.status -eq "ok") {
            Write-Host "Health check response: $($res | ConvertTo-Json -Compress)"
            $healthy = $true
            break
        }
    } catch {
        Write-Host "Waiting... ($($_.Exception.Message))"
    }
    Start-Sleep -Seconds 5
}

if (-not $healthy) {
    throw "Health check verification failed for $Service"
}

Write-Host "==> Deployment of $Service ($tag) completed successfully at $serviceUrl!"
