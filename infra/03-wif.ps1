# 03-wif.ps1 - Configure Workload Identity Federation
$ErrorActionPreference = "Stop"
$ProjectId = if ($env:GCP_PROJECT) { $env:GCP_PROJECT } else { (gcloud.cmd config get-value project) }
$ProjectNumber = (& gcloud.cmd projects describe $ProjectId --format="value(projectNumber)").Trim()
$Repo = if ($env:GITHUB_REPOSITORY) { $env:GITHUB_REPOSITORY } else { "gxobst/handover-copilot" }
$PoolId = "github-pool"
$ProviderId = "github-provider"
$DeployerEmail = "handover-deployer@$ProjectId.iam.gserviceaccount.com"

Write-Host "==> Checking Workload Identity Pool $PoolId..."
$poolExists = & gcloud.cmd iam workload-identity-pools describe $PoolId --location="global" --project=$ProjectId 2>$null
if (-not $poolExists) {
    & gcloud.cmd iam workload-identity-pools create $PoolId --location="global" --display-name="GitHub Actions Pool" --project=$ProjectId
}

$providerExists = & gcloud.cmd iam workload-identity-pools providers describe $ProviderId --workload-identity-pool=$PoolId --location="global" --project=$ProjectId 2>$null
if (-not $providerExists) {
    & gcloud.cmd iam workload-identity-pools providers create-oidc $ProviderId `
      --workload-identity-pool=$PoolId `
      --location="global" `
      --issuer-uri="https://token.actions.githubusercontent.com" `
      --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner" `
      --attribute-condition="assertion.repository == '$Repo'" `
      --project=$ProjectId
}

$member = "principalSet://iam.googleapis.com/projects/$ProjectNumber/locations/global/workloadIdentityPools/$PoolId/attribute.repository/$Repo"
& gcloud.cmd iam service-accounts add-iam-policy-binding $DeployerEmail --role="roles/iam.workloadIdentityUser" --member=$member --project=$ProjectId --quiet | Out-Null
Write-Host "==> WIF configured for $Repo."
