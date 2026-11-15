# ==============================================================================
# 05-database.ps1 - Provision AlloyDB Express Database Persistence in europe-west2
# Matches plan.md §6 & §14: AlloyDB cluster with scale-to-zero compute (PostgreSQL 18).
# Idempotent: safe to run multiple times.
# ==============================================================================
[CmdletBinding()]
param(
    [string]$ProjectId = $env:GCP_PROJECT,
    [string]$Region = "europe-west2",
    [string]$ClusterId = "handover-cluster",
    [string]$InstanceId = "handover-primary",
    [string]$DbPassword = "Yg0vCNCSfVTNpicWso_EBwDqvk4Vd9V1"
)

$ErrorActionPreference = "Stop"

if (-not $ProjectId) {
    $ProjectId = & "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" config get-value project 2>$null
}
if (-not $ProjectId) {
    Write-Error "ERROR: ProjectId is required and could not be determined from gcloud config."
}

Write-Host "==> Configuring AlloyDB persistence in '$Region' (project: $ProjectId)..."

# Check if cluster exists
$clusterCheck = & "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" alloydb clusters describe $ClusterId --region=$Region --project=$ProjectId 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "AlloyDB cluster '$ClusterId' already exists."
} else {
    Write-Host "Creating AlloyDB cluster '$ClusterId' (PostgreSQL 18) with Private Service Connect..."
    & "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" alloydb clusters create $ClusterId `
        --region=$Region `
        --project=$ProjectId `
        --password=$DbPassword `
        --database-version="POSTGRES_18" `
        --enable-private-service-connect
}

# Check if primary instance exists
$instCheck = & "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" alloydb instances describe $InstanceId --cluster=$ClusterId --region=$Region --project=$ProjectId 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "AlloyDB primary instance '$InstanceId' already exists."
} else {
    Write-Host "Creating AlloyDB primary instance '$InstanceId' (1 vCPU)..."
    & "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" alloydb instances create $InstanceId `
        --cluster=$ClusterId `
        --region=$Region `
        --project=$ProjectId `
        --instance-type="PRIMARY" `
        --cpu-count=1
}

Write-Host "Waiting for AlloyDB primary instance '$InstanceId' to become READY..."
while ($true) {
    $state = & "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" alloydb instances describe $InstanceId --cluster=$ClusterId --region=$Region --project=$ProjectId --format="value(state)" 2>$null
    Write-Host "Current instance state: $state"
    if ($state -eq "READY") {
        break
    }
    Start-Sleep -Seconds 15
}

$ip = & "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" alloydb instances describe $InstanceId --cluster=$ClusterId --region=$Region --project=$ProjectId --format="value(ipAddress)" 2>$null
Write-Host "AlloyDB instance '$InstanceId' is READY (IP: $ip)."

$databaseUrl = "postgresql+psycopg://postgres:${DbPassword}@${ip}:5432/postgres"

Write-Host "Updating DATABASE_URL in Secret Manager..."
$tempFile = [System.IO.Path]::GetTempFileName()
[System.IO.File]::WriteAllText($tempFile, $databaseUrl)
& "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" secrets versions add "DATABASE_URL" --data-file=$tempFile --project=$ProjectId
Remove-Item $tempFile -Force -ErrorAction SilentlyContinue

Write-Host "==> AlloyDB cluster '$ClusterId' / instance '$InstanceId' configured successfully."
