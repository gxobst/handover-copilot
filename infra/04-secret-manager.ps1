# 04-secret-manager.ps1 - Provision Secret Manager Secrets
$ErrorActionPreference = "Stop"
$ProjectId = if ($env:GCP_PROJECT) { $env:GCP_PROJECT } else { (gcloud.cmd config get-value project) }
$RuntimeEmail = "handover-runtime@$ProjectId.iam.gserviceaccount.com"

function Ensure-Secret($name, $val) {
    $exists = & gcloud.cmd secrets describe $name --project=$ProjectId 2>$null
    if (-not $exists) {
        Write-Host "Creating secret $name..."
        & gcloud.cmd secrets create $name --replication-policy="automatic" --project=$ProjectId
    }
    $versions = & gcloud.cmd secrets versions list $name --project=$ProjectId --format="value(name)" 2>$null
    if (-not $versions) {
        Write-Host "Adding version to $name..."
        $val | & gcloud.cmd secrets versions add $name --data-file=- --project=$ProjectId | Out-Null
    }
    & gcloud.cmd secrets add-iam-policy-binding $name --member="serviceAccount:$RuntimeEmail" --role="roles/secretmanager.secretAccessor" --project=$ProjectId --quiet | Out-Null
}

$adminToken = if ($env:ADMIN_TOKEN) { $env:ADMIN_TOKEN } else { [System.Guid]::NewGuid().ToString("N") }
Ensure-Secret "ADMIN_TOKEN" $adminToken

$relayToken = if ($env:RELAY_WEBHOOK_TOKEN) { $env:RELAY_WEBHOOK_TOKEN } else { [System.Guid]::NewGuid().ToString("N") }
Ensure-Secret "RELAY_WEBHOOK_TOKEN" $relayToken

$dbUrl = if ($env:DATABASE_URL) { $env:DATABASE_URL } else { "postgresql+psycopg://postgres:Yg0vCNCSfVTNpicWso_EBwDqvk4Vd9V1@/handover?host=/cloudsql/$ProjectId:europe-west2:handover-db" }
Ensure-Secret "DATABASE_URL" $dbUrl

$pat = if ($env:GITHUB_DISPATCH_PAT) { $env:GITHUB_DISPATCH_PAT } else { "dummy-pat" }
Ensure-Secret "GITHUB_DISPATCH_PAT" $pat

Write-Host "==> Secrets provisioned."
