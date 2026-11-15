# 06-cloud-run-migrate-job.ps1 - Provision Cloud Run Database Migration Job
$ErrorActionPreference = "Stop"
$ProjectId = if ($env:GCP_PROJECT) { $env:GCP_PROJECT } else { (gcloud.cmd config get-value project) }
$Region = if ($env:GCP_REGION) { $env:GCP_REGION } else { "europe-west2" }
$Repo = if ($env:ARTIFACT_REPO) { $env:ARTIFACT_REPO } else { "handover" }
$Tag = if ($env:IMAGE_TAG) { $env:IMAGE_TAG } else { "latest" }
$ImageUri = "$Region-docker.pkg.dev/$ProjectId/$Repo/app:$Tag"
$JobName = "handover-migrate"
$RuntimeEmail = "handover-runtime@$ProjectId.iam.gserviceaccount.com"
$CloudSqlConn = "$ProjectId`:$Region`:handover-db"

$jobExists = & gcloud.cmd run jobs describe $JobName --region=$Region --project=$ProjectId 2>$null
$flags = @(
  "--image=$ImageUri",
  "--region=$Region",
  "--project=$ProjectId",
  "--service-account=$RuntimeEmail",
  "--set-secrets=DATABASE_URL=DATABASE_URL:latest",
  "--set-cloudsql-instances=$CloudSqlConn",
  "--command=uv",
  "--args=run,alembic,upgrade,head",
  "--max-retries=1",
  "--task-timeout=300s",
  "--cpu=1",
  "--memory=512Mi"
)

if ($jobExists) {
    Write-Host "Updating Cloud Run Job $JobName..."
    & gcloud.cmd run jobs update $JobName @flags
} else {
    Write-Host "Creating Cloud Run Job $JobName..."
    & gcloud.cmd run jobs create $JobName @flags
}
Write-Host "==> Cloud Run Job $JobName configured."
