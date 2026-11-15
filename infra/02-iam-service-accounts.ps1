# 02-iam-service-accounts.ps1 - Provision Service Accounts and IAM Roles
$ErrorActionPreference = "Stop"
$ProjectId = if ($env:GCP_PROJECT) { $env:GCP_PROJECT } else { (gcloud.cmd config get-value project) }
$DeployerEmail = "handover-deployer@$ProjectId.iam.gserviceaccount.com"
$RuntimeEmail = "handover-runtime@$ProjectId.iam.gserviceaccount.com"

Write-Host "==> Checking service accounts..."
$deployerExists = & gcloud.cmd iam service-accounts describe $DeployerEmail --project=$ProjectId 2>$null
if (-not $deployerExists) {
    & gcloud.cmd iam service-accounts create "handover-deployer" --display-name="Shift Handover CI/CD Deployer" --project=$ProjectId
}
$runtimeExists = & gcloud.cmd iam service-accounts describe $RuntimeEmail --project=$ProjectId 2>$null
if (-not $runtimeExists) {
    & gcloud.cmd iam service-accounts create "handover-runtime" --display-name="Shift Handover Cloud Run Runtime" --project=$ProjectId
}

$deployerRoles = @("roles/run.admin", "roles/artifactregistry.writer", "roles/iam.serviceAccountUser", "roles/run.developer")
foreach ($role in $deployerRoles) {
    & gcloud.cmd projects add-iam-policy-binding $ProjectId --member="serviceAccount:$DeployerEmail" --role=$role --condition=None --quiet | Out-Null
}

$runtimeRoles = @("roles/aiplatform.user", "roles/secretmanager.secretAccessor", "roles/alloydb.client", "roles/alloydb.databaseUser", "roles/cloudsql.client")
foreach ($role in $runtimeRoles) {
    & gcloud.cmd projects add-iam-policy-binding $ProjectId --member="serviceAccount:$RuntimeEmail" --role=$role --condition=None --quiet | Out-Null
}

& gcloud.cmd iam service-accounts add-iam-policy-binding $RuntimeEmail --member="serviceAccount:$DeployerEmail" --role="roles/iam.serviceAccountUser" --project=$ProjectId --quiet | Out-Null
Write-Host "==> Service accounts and IAM configured."
